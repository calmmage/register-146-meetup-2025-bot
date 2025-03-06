# Refactoring Plan for 146 Meetup Register Bot

## Current Structure
- `app.py`: Core application logic, including payment calculations and database operations
- `router.py`: Telegram bot handlers and routing
- `bot.py`: Bot initialization and setup

## Planned Structure

### Core Files
- `app.py`: Core application logic (non-payment related)
- `bot.py`: Bot initialization and setup
- `router.py`: Main router with non-payment related handlers

### Payment Module
- `payment/models.py`: Payment data models
  - `PaymentStatus` enum
  - `Payment` class
- `payment/service.py`: Payment business logic
  - `PaymentService` class with methods:
    - `calculate_payment_amount`
    - `save_payment_info`
    - `update_payment_status`
    - `process_payment_screenshot`
    - `forward_screenshot_to_validation_chat`
- `payment/router.py`: Payment-related handlers
  - `pay_handler`
  - `process_payment`
  - `payment_verification_callback`
  - `handle_payment_screenshot`

## Implementation Plan
1. Create the payment module structure
2. Extract payment-related code from app.py to payment/service.py
3. Extract payment-related handlers from router.py to payment/router.py
4. Wire everything together
5. Test the functionality

## Current Focus
Implementing the screenshot forwarding feature to the validation chat. 