# Timeout Handling Fixes

## Overview
We've fixed several issues related to timeout handling in the ask_user family of functions. When these functions time out, they return `None`, which was causing errors in the code that expected valid responses.

## Changes Made

### 1. Fix in `validate_full_name` function (app.py)
- Added a check for None input before attempting to use the input
- Returns a user-friendly error message to be displayed

### 2. Fix in city selection (router.py)
- Added a check for None response after asking for city choice
- Added proper user notification and exit from the registration flow
- Prevents the ValueError when trying to convert None to TargetCity

### 3. Fix in full name input (router.py)
- Added a check for None response after asking for user's full name
- Shows a timeout message and exits the registration flow
- Prevents the AttributeError when calling strip() on None

### 4. Fix in graduation year and class input (router.py)
- Added a check for None response after asking for graduation year and class
- Shows a timeout message and exits the registration flow
- Prevents potential errors when parsing None

### 5. Fixed custom payment amount handling (payment.py)
- Added proper handling of None response in payment amount input
- Added logging of timeout events
- Cancels the operation with clear message to admin
- Maintains a simple flow without unnecessary retries

## Benefits
- More robust handling of network issues and timeout scenarios
- Better user experience with clear error messages
- Prevents crashes that were happening in production
- Adds retries for admin operations where appropriate

## Technical Details
- All modifications maintain the existing application flow
- No changes to the database schema or API interfaces
- Error messages are consistent with the application's style