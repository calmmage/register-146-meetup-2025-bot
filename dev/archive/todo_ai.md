# Todo List

## Current Tasks
- "When we get a screenshot -> forward it to validation chat"

## Completed Tasks
- ✅ Include payment amount provided by admin in payment status
- ✅ Log payment amount in payment verification messages
- ✅ Add payment status and amount to CSV and Google Sheets exports
- ✅ Add support for PDF files in payment screenshots

## Future Tasks
- "Логика мотивации скинуться больше чем минималку (или если меньше чем минималку то более агрессивно трясти)"
- "Отслеживать траншами кто скинулся и когда, чтобы это падало в табличку какую-то по каждому участнику когда заплатил и сколько, и хватает ли на минимальный / рекомендуемый взнос"
- "Валидация платежа админом: сверка скрина с выпиской по карте"
- "Если размер взноса меньше минимума, бот пишет пользователю 'Привет! Будет здорово, если ты внесешь еще чуть-чуть для организации встречи выпускников'"
- "Если размер взноса больше или равен минимуму, бот пишет юзеру 'Взнос подтвержден, спасибо!'"

## Bug Fixes
- Fix state data initialization in all places where `process_payment` is called
  - ✅ Fixed in `register_user` function
  - ✅ Fixed in `pay_handler` function
  - ✅ Confirmed `pay_now_callback` already initializes state data correctly
  - ✅ All places where `process_payment` is called have been checked
- Payment amount showing as 0 in database
  - The `payment_amount` field is only set when an admin confirms the payment and enters the amount manually
  - When a user submits a payment screenshot, we save `discounted_payment_amount` and `regular_payment_amount`, but not `payment_amount`
  - Consider using `discounted_payment_amount` as default for `payment_amount` when confirming payments

## Type Errors
- Fix type errors in app/app.py and app/router.py
  - Add proper type annotations for optional parameters
  - Add proper null checks

## Code Improvements
- Review and refactor payment processing flow
- Consider creating a helper function to initialize state data before calling `process_payment` 