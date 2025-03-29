

## Iteration 1
- ask user the location - Moscow, Perm or Piter
- ask user their name
- ask user graduation year
- save info to the database


## Iteration 2


## Later?
- log events to the logging chat
- as
- 
- manual validation -> write to admin / chat (who validates first)

# `ask_user` Timeout Handling Issues

## Error Types Found
1. `ValueError: None is not a valid TargetCity` - When `ask_user` returns None instead of a city selection
   - File: `/app/app/router.py`, line 485
   - Function: `register_user`
   - Error occurs when trying to convert a None response to a TargetCity enum

2. `AttributeError: 'NoneType' object has no attribute 'strip'` - When `ask_user` returns None for text input
   - File: `/app/app/router.py`, line 567-568 (validate_full_name)
   - Function: `register_user`
   - Error occurs when validating full_name but response is None
   - File: `/app/app/app.py`, line 204-205
   - `words = full_name.strip().split()`

3. `None` handling issues in custom payment amount entry
   - File: `/app/app/routers/payment.py`, line 623-634
   - Function: `confirm_payment_callback`
   - When asking for custom payment amount from admin, it handles None but doesn't provide retry

## Locations Requiring Fixes
1. Router.py:485 - Needs to handle None response when selecting city
2. Router.py:567 - Needs to handle None response when validating full_name
3. App.py:204 - The validate_full_name function needs to handle None input
4. Payment.py:623-634 - The confirm_payment_callback function needs a better way to handle None responses

## Recommended Solutions
1. Add None checks before attempting to use responses from ask_user functions
2. Implement retry mechanisms when timeouts occur
3. Update validation functions to handle None inputs gracefully
4. Consider extending timeout periods for critical operations
5. Add more comprehensive error logging for these scenarios