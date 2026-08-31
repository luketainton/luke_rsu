# RSU Ledger UK

A small, local-first ledger for a UK taxpayer receiving USD-denominated RSUs. It records grants, vesting and sales, converts each event to GBP using the rate you enter, and provides a transparent share-matching CGT estimate.

## Run locally

```sh
npm install
npm run dev
```

All information lives in browser local storage. **Export CSV** regularly; no data leaves the browser.

## Exchange rates

Every vest and sale keeps its own GBP-per-USD rate: both the acquisition/taxable amount and disposal proceeds are converted into sterling at their respective dates. The **HMRC rate sources** button stores published [spot](https://www.trade-tariff.service.gov.uk/exchange_rates/spot), [monthly](https://www.trade-tariff.service.gov.uk/exchange_rates/monthly), or [average](https://www.trade-tariff.service.gov.uk/exchange_rates/average) rates (entered as HMRC's `USD per GBP` quote) and links the selected type, period and source URL to a transaction. You can still enter a spot or broker rate directly.

HMRC does not prescribe a single CGT exchange-rate reference point; use a reasonable, consistent method and retain the evidence. HMRC's average-rate publications cover rolling 12-month periods ending 31 March and 31 December; their monthly-rate service is intended for customs valuation. Do not use a later rate to convert a final USD gain—all costs and proceeds are converted separately on their relevant dates.

## Important scope

This is a record-keeping aid, not tax advice or a completed Self Assessment return. It does not calculate Income Tax/NIC, nor the final CGT liability, annual exempt amount or tax rate. Enter the employer-confirmed taxable vest value and deductions, and retain the original payslip, broker statements, grant documents and FX evidence.

The disposal view approximates the UK identification order for ordinary listed shares: same-day acquisitions, acquisitions in the following 30 days, then the Section 104 pool. It requires the complete history of acquisitions for the particular share class to be reliable. Overseas duties, restricted/non-listed securities, share elections and corporate actions need specialist review.

## References

- [HMRC HS305 Employment-related shares and securities (2026)](https://www.gov.uk/government/publications/employee-shares-and-securities-further-guidance-hs305-self-assessment-helpsheet/hs305-employment-related-shares-and-securities-further-guidance-2026)
- [HMRC Capital Gains manual: share identification](https://www.gov.uk/hmrc-internal-manuals/capital-gains-manual/cg51550)
- [HMRC Capital Gains manual: foreign currency assets](https://www.gov.uk/hmrc-internal-manuals/capital-gains-manual/cg78310)
- [HMRC average exchange rates](https://www.trade-tariff.service.gov.uk/exchange_rates/average)
- [HMRC employee share scheme overview](https://www.gov.uk/tax-employee-share-schemes)
- [RPP: Restricted Securities / RSUs](https://rppaccounts.co.uk/restricted-share-units/)
- [Frazer James: RSUs guide](https://frazerjames.co.uk/rsus-a-tech-employees-guide-2/)
