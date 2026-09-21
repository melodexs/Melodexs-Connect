# MELODEXS CONNECT Rebrand Checkpoint

This backup restores the MELODEXS CONNECT branding work from the available project backup.

## Branding
- Product name: MELODEXS CONNECT
- Primary blue: #0251B0
- Lime accent: #D1FF42
- Light neutral: #C7D1DD
- Supporting background: #F5F8FC
- Supporting text: #172033 / #667085

## Updated
- Customer-facing HTML page titles, headings, messages and footers
- Navigation/logo treatment across pages
- Homepage branding
- Admin page branding
- API status and customer-facing API/email messages
- Server startup branding
- Active project documentation descriptions
- Old green UI colors replaced with MELODEXS palette
- Buy Data plan labels hide the provider's leading denomination while preserving the original WiseSub plan internally

## Preserved intentionally
- `cheapdataUser`, `cheapdataUserId`, and `cheapdataNewUserId` localStorage keys
- `CHEAPDATA_*` environment variable names
- Existing SQLite database paths and schema
- Existing package/workspace identifiers
- Existing WiseSub and payment logic

These internal identifiers are preserved so the rebrand does not break existing application behavior.

## Important
The MongoDB Atlas migration was not completed in this checkpoint. This backup should be pushed to GitHub before continuing that migration.
