# RSU Ledger UK

A small, local-first ledger for a UK taxpayer receiving USD-denominated RSUs. It records grants, vesting and sales, converts each event to GBP using the rate you enter, and provides a transparent share-matching CGT estimate.

## Run locally

```sh
npm install
npm run dev
```

All information lives in browser local storage. **Export CSV** regularly; no data leaves the browser.

## Important scope

This is a record-keeping aid, not tax advice or a completed Self Assessment return. It does not calculate Income Tax/NIC, nor the final CGT liability, annual exempt amount or tax rate. Enter the employer-confirmed taxable vest value and deductions, and retain the original payslip, broker statements, grant documents and FX evidence.

The disposal view approximates the UK identification order for ordinary listed shares: same-day acquisitions, acquisitions in the following 30 days, then the Section 104 pool. It requires the complete history of acquisitions for the particular share class to be reliable. Overseas duties, restricted/non-listed securities, share elections and corporate actions need specialist review.

## References

- [HMRC HS305 Employment-related shares and securities (2026)](https://www.gov.uk/government/publications/employee-shares-and-securities-further-guidance-hs305-self-assessment-helpsheet/hs305-employment-related-shares-and-securities-further-guidance-2026)
- [HMRC Capital Gains manual: share identification](https://www.gov.uk/hmrc-internal-manuals/capital-gains-manual/cg51550)
- [HMRC employee share scheme overview](https://www.gov.uk/tax-employee-share-schemes)
- [RPP: Restricted Securities / RSUs](https://rppaccounts.co.uk/restricted-share-units/)
- [Frazer James: RSUs guide](https://frazerjames.co.uk/rsus-a-tech-employees-guide-2/)
