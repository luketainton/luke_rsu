import 'dotenv/config';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import express from 'express';
import session from 'express-session';
import pgSession from 'connect-pg-simple';
import passport from 'passport';
import { Issuer, Strategy as OidcStrategy } from 'openid-client';
import argon2 from 'argon2';
import pg from 'pg';

const { Pool } = pg;
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const port = Number(process.env.PORT || 3000);
const appUrl = process.env.APP_URL || `http://localhost:${port}`;
const authMode = process.env.AUTH_MODE || 'local'; // local, oidc, hybrid
if (!process.env.DATABASE_URL) throw new Error('DATABASE_URL is required');
if (process.env.NODE_ENV === 'production' && (!process.env.SESSION_SECRET || process.env.SESSION_SECRET.length < 32)) throw new Error('A SESSION_SECRET of at least 32 characters is required in production');
const pool = new Pool({ connectionString: process.env.DATABASE_URL });
const PgStore = pgSession(session);
const app = express();
app.set('trust proxy', 1);
app.use(express.json({ limit: '1mb' }));
app.use(session({
  store: new PgStore({ pool, tableName: 'user_sessions', createTableIfMissing: true }),
  secret: process.env.SESSION_SECRET || 'development-only-change-me',
  resave: false, saveUninitialized: false,
  cookie: { httpOnly: true, sameSite: 'lax', secure: appUrl.startsWith('https://'), maxAge: 1000 * 60 * 60 * 12 },
}));
app.use(passport.initialize()); app.use(passport.session());
passport.serializeUser((user, done) => done(null, user.id));
passport.deserializeUser(async (id, done) => { try { const { rows } = await pool.query('SELECT id, email, display_name, is_system_admin FROM users WHERE id=$1', [id]); done(null, rows[0] || false); } catch (e) { done(e); } });

const emptyLedger = { company: '', ticker: '', grants: [], vests: [], sales: [], rates: [] };
const allowedLedgerKeys = new Set(['company', 'ticker', 'grants', 'vests', 'sales', 'rates']);
function cleanLedger(input) { if (!input || typeof input !== 'object' || Array.isArray(input)) throw new Error('Ledger must be an object'); const out = {}; for (const key of allowedLedgerKeys) out[key] = input[key] ?? structuredClone(emptyLedger[key]); if (typeof out.company !== 'string' || typeof out.ticker !== 'string' || !['grants','vests','sales','rates'].every(k => Array.isArray(out[k]))) throw new Error('Invalid ledger structure'); return out; }
async function personalWorkspace(user) { const existing = await pool.query(`SELECT w.id,w.name,m.role FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=$1 AND m.role='owner' ORDER BY w.created_at LIMIT 1`, [user.id]); if (existing.rows[0]) return existing.rows[0]; const client = await pool.connect(); try { await client.query('BEGIN'); const { rows:[workspace] } = await client.query('INSERT INTO workspaces(name) VALUES($1) RETURNING id,name', [`${user.display_name}'s private ledger`]); await client.query('INSERT INTO workspace_members(workspace_id,user_id,role) VALUES($1,$2,\'owner\')', [workspace.id,user.id]); await client.query('INSERT INTO ledger_snapshots(workspace_id,document) VALUES($1,$2)', [workspace.id, emptyLedger]); await client.query('COMMIT'); return { ...workspace, role: 'owner' }; } catch (e) { await client.query('ROLLBACK'); throw e; } finally { client.release(); } }
async function membership(workspaceId, userId) { const { rows } = await pool.query('SELECT role FROM workspace_members WHERE workspace_id=$1 AND user_id=$2', [workspaceId, userId]); return rows[0]?.role; }
function requireAuth(req,res,next){ if (!req.user) return res.status(401).json({ error:'Authentication required' }); next(); }
function requireSystemAdmin(req,res,next){ if (!req.user?.is_system_admin) return res.status(403).json({error:'System administrator permission required'}); next(); }
function roleAtLeast(role, required){ return ['viewer','editor','owner'].indexOf(role) >= ['viewer','editor','owner'].indexOf(required); }
function requireRole(required){ return async (req,res,next) => { const workspaceId=req.params.workspaceId || req.query.workspaceId || req.body?.workspaceId; if (!workspaceId) return res.status(400).json({error:'workspaceId is required'}); const role=await membership(workspaceId,req.user.id); if (!role || !roleAtLeast(role,required)) return res.status(403).json({error:'Insufficient workspace permission'}); req.workspaceId=workspaceId; req.workspaceRole=role; next(); }; }

if (authMode === 'oidc' || authMode === 'hybrid') {
  if (!process.env.OIDC_ISSUER_URL || !process.env.OIDC_CLIENT_ID || !process.env.OIDC_CLIENT_SECRET) throw new Error('OIDC_ISSUER_URL, OIDC_CLIENT_ID and OIDC_CLIENT_SECRET are required for OIDC');
  const issuer = await Issuer.discover(process.env.OIDC_ISSUER_URL);
  const client = new issuer.Client({ client_id: process.env.OIDC_CLIENT_ID, client_secret: process.env.OIDC_CLIENT_SECRET, redirect_uris:[`${appUrl}/auth/oidc/callback`], response_types:['code'] });
  passport.use('oidc', new OidcStrategy({ client, params:{ scope:'openid profile email' } }, async (tokenSet, userinfo, done) => { try { if (userinfo.email_verified === false) return done(new Error('OIDC provider did not verify the email address')); const subject=userinfo.sub; const email=(userinfo.email || `${subject}@oidc.invalid`).toLowerCase(); const name=userinfo.name || userinfo.preferred_username || email; let { rows }=await pool.query('SELECT id,email,display_name,is_system_admin FROM users WHERE oidc_subject=$1 OR email=$2', [subject,email]); let user=rows[0]; if (!user) { ({ rows:[user] }=await pool.query('INSERT INTO users(email,display_name,oidc_subject) VALUES($1,$2,$3) RETURNING id,email,display_name,is_system_admin',[email,name,subject])); } else if (!user.oidc_subject) { await pool.query('UPDATE users SET oidc_subject=$1,display_name=$2 WHERE id=$3',[subject,name,user.id]); user={...user,display_name:name}; } await personalWorkspace(user); done(null,user); } catch(e){done(e);} }));
  app.get('/auth/oidc', passport.authenticate('oidc'));
  app.get('/auth/oidc/callback', passport.authenticate('oidc', { failureRedirect:'/login?error=oidc' }), (req,res)=>res.redirect('/'));
}

app.post('/auth/local/login', async (req,res) => { if (authMode === 'oidc') return res.status(404).end(); const { email,password }=req.body || {}; if (!email || !password) return res.status(400).json({error:'Email and password are required'}); const { rows }=await pool.query('SELECT * FROM users WHERE email=$1',[String(email).toLowerCase()]); const user=rows[0]; if (!user?.password_hash || !await argon2.verify(user.password_hash,password)) return res.status(401).json({error:'Invalid credentials'}); await personalWorkspace(user); req.login(user,err=>err ? res.status(500).json({error:'Could not create session'}) : res.json({ok:true})); });
app.post('/auth/local/bootstrap', async (req,res) => { if (authMode === 'oidc') return res.status(404).end(); const { email,password,displayName }=req.body || {}; if (!email || !password || String(password).length<14) return res.status(400).json({error:'Email and a password of at least 14 characters are required'}); const count=await pool.query('SELECT count(*)::int AS count FROM users'); if (count.rows[0].count) return res.status(403).json({error:'Bootstrap is only available before the first user exists'}); const hash=await argon2.hash(password); const { rows:[user] }=await pool.query('INSERT INTO users(email,display_name,password_hash,is_system_admin) VALUES($1,$2,$3,true) RETURNING id,email,display_name,is_system_admin',[String(email).toLowerCase(),displayName || email,hash]); await personalWorkspace(user); req.login(user,err=>err ? res.status(500).json({error:'Could not create session'}) : res.status(201).json({ok:true})); });
app.post('/auth/logout',(req,res,next)=>req.logout(err=>err?next(err):req.session.destroy(()=>res.status(204).end())));

app.get('/auth/config', (_req,res)=>res.json({ authMode }));
app.get('/api/me', requireAuth, async (req,res) => { const { rows }=await pool.query('SELECT w.id,w.name,m.role FROM workspaces w JOIN workspace_members m ON m.workspace_id=w.id WHERE m.user_id=$1 ORDER BY w.created_at',[req.user.id]); res.json({ user:req.user, workspaces:rows }); });
app.get('/api/ledger', requireAuth, async (req,res) => { const workspaceId=req.query.workspaceId || (await personalWorkspace(req.user)).id; const role=await membership(workspaceId,req.user.id); if (!role) return res.status(403).json({error:'Not a workspace member'}); const { rows }=await pool.query('SELECT document,updated_at FROM ledger_snapshots WHERE workspace_id=$1',[workspaceId]); res.json({ workspaceId, role, ledger:rows[0]?.document || emptyLedger, updatedAt:rows[0]?.updated_at }); });
app.put('/api/ledger', requireAuth, requireRole('editor'), async (req,res) => { try { const ledger=cleanLedger(req.body.ledger); await pool.query('INSERT INTO ledger_snapshots(workspace_id,document,updated_at) VALUES($1,$2,now()) ON CONFLICT(workspace_id) DO UPDATE SET document=EXCLUDED.document,updated_at=now()',[req.workspaceId,ledger]); res.json({ok:true}); } catch(e){res.status(400).json({error:e.message});} });
app.get('/api/workspaces/:workspaceId/members', requireAuth, requireRole('owner'), async (req,res) => { const { rows }=await pool.query('SELECT u.id,u.email,u.display_name,m.role FROM workspace_members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=$1 ORDER BY u.email',[req.workspaceId]);res.json(rows); });
app.post('/api/workspaces/:workspaceId/members', requireAuth, requireRole('owner'), async (req,res) => { const { email,role }=req.body || {}; if (!email || !['owner','editor','viewer'].includes(role)) return res.status(400).json({error:'Valid email and role required'}); const { rows }=await pool.query('SELECT id FROM users WHERE email=$1',[String(email).toLowerCase()]); if(!rows[0])return res.status(404).json({error:'User must sign in once before access can be granted'}); await pool.query('INSERT INTO workspace_members(workspace_id,user_id,role) VALUES($1,$2,$3) ON CONFLICT(workspace_id,user_id) DO UPDATE SET role=EXCLUDED.role',[req.workspaceId,rows[0].id,role]);res.status(201).json({ok:true}); });
app.delete('/api/workspaces/:workspaceId/members/:userId', requireAuth, requireRole('owner'), async (req,res) => { if(req.params.userId===req.user.id)return res.status(400).json({error:'An owner cannot remove themselves'});await pool.query('DELETE FROM workspace_members WHERE workspace_id=$1 AND user_id=$2',[req.workspaceId,req.params.userId]);res.status(204).end(); });
app.get('/api/users', requireAuth, requireSystemAdmin, async (_req,res)=>{ const { rows }=await pool.query('SELECT id,email,display_name,is_system_admin,created_at FROM users ORDER BY email');res.json(rows); });
app.post('/api/users', requireAuth, requireSystemAdmin, async (req,res)=>{ const {email,displayName,password,isSystemAdmin=false}=req.body||{};if(!email||!displayName||!password||String(password).length<14)return res.status(400).json({error:'Email, display name and password (14+ characters) are required'});try{const hash=await argon2.hash(password);const {rows:[user]}=await pool.query('INSERT INTO users(email,display_name,password_hash,is_system_admin) VALUES($1,$2,$3,$4) RETURNING id,email,display_name,is_system_admin',[String(email).toLowerCase(),displayName,hash,Boolean(isSystemAdmin)]);await personalWorkspace(user);res.status(201).json(user);}catch(e){if(e.code==='23505')return res.status(409).json({error:'Email already exists'});throw e;} });

app.use(express.static(path.join(__dirname,'../dist')));
app.get('/healthz', async (_req,res)=>{try{await pool.query('SELECT 1');res.json({ok:true});}catch{res.status(503).json({ok:false});}});
app.get('/login', (_req,res)=>res.sendFile(path.join(__dirname,'../dist/index.html')));
app.get('/{*splat}', (_req,res)=>res.sendFile(path.join(__dirname,'../dist/index.html')));
app.use((err,_req,res,_next)=>{console.error(err);res.status(500).json({error:'Internal server error'});});
app.listen(port,()=>console.log(`RSU Ledger listening on ${port}`));
