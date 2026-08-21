# Customer identity V1

`User` is the global consumer account. It owns the authenticated profile and stable Google
subject. `Customer` remains the tenant-scoped relationship between that person and one business.
`CustomerAccountLink` connects both only after an explicit booking context or a single,
unambiguous normalized-phone match during an authenticated booking.

Phone matching uses E.164 through `phonenumbers`; normalization never marks a phone as verified.
Manual Instagram usernames are normalized but remain unverified and separate from a future
provider user ID. Names and manual Instagram values are never merge signals.

The customer can see their own linked bookings across businesses. Business endpoints continue to
query `Customer` by tenant and never expose the account link or cross-business history.

V2 can add identities or preferences around the global account without changing tenant ownership:
verified providers can populate the reserved provider ID fields, while favorites, recurrence,
recommendations and consent records can reference the global account independently. TikTok,
marketing inference, loyalty and cross-business discovery are deliberately outside V1.
