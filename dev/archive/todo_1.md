# Payment Flow Implementation

## Payment Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│ Main Entry Points                                           │
├─────────────────┬───────────────────────┬───────────────────┤
│ 1. End of       │ 2. /start for         │ 3. /pay command   │
│ registration    │ registered user       │                   │
│ flow            │ who hasn't paid       │                   │
└─────────┬───────┴──────────┬────────────┴────────┬──────────┘
          │                  │                     │
          ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│ Check if payment is needed (not St. Petersburg)             │
└───────────────────────────────┬─────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│ Calculate payment amount                                    │
└───────────────────────────────┬─────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────┐
│ Decision: Has user seen payment instructions before?        │
└───────────────┬───────────────────────────────┬─────────────┘
                │                               │
                │ No                            │ Yes
                ▼                               │
┌───────────────────────────────┐               │
│ Send payment instructions     │               │
│ (3 messages with details)     │               │
└───────────────┬───────────────┘               │
                │                               │
                ▼                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Request screenshot with "Pay Later" button                  │
└───────────────────────────────┬─────────────────────────────┘
                                │
                ┌───────────────┴───────────────┐
                │                               │
                ▼                               ▼
┌───────────────────────────┐     ┌───────────────────────────┐
│ User sends screenshot     │     │ User clicks "Pay Later"   │
└───────────────┬───────────┘     └───────────────┬───────────┘
                │                                 │
                ▼                                 ▼
┌───────────────────────────┐     ┌───────────────────────────┐
│ Save payment info &       │     │ Save pending payment      │
│ forward to events chat    │     │ status                    │
└───────────────┬───────────┘     └───────────────────────────┘
                │
                ▼
┌───────────────────────────┐
│ Admin validates with      │
│ /validate or /decline     │
└───────────────┬───────────┘
                │
                ▼
┌───────────────────────────┐
│ Update payment status &   │
│ notify user               │
└───────────────────────────┘
```

## Implementation Notes

1. **Entry Points**:
   - End of registration flow in `app/router.py`
   - /start command for registered users who haven't paid
   - /pay command for manual payment initiation

2. **Key Improvements**:
   - Separated payment instructions from screenshot request
   - Added logic to avoid showing instructions repeatedly
   - Integrated payment into the main registration flow
   - Added payment status check in /start flow
   - Fixed the "pay later" button to use inline callbacks

3. **Admin Validation**:
   - Admins use /validate and /decline commands
   - Commands are used as replies to payment screenshots
   - Validation results are logged and users are notified

4. **Future Improvements**:
   - Add payment reminders for users who chose "pay later"
   - Implement payment statistics for admins
   - Add ability to manually mark payments as confirmed without screenshots
   - Improve error handling for payment validation 