- [x] add 3 new buttons to payment validation: confirm minimal, confirm regular (value), if different - confirm formula (value), confirm custom - ask. 
- [ ] database is missing proper formula values (because i updated the code mid-way) - detect and re-add them. (add a custom func _check_database_payment_value -> generate proper formula, compare and if missing add to db. )
- [x] include deleted users in payment statistics

# Promo
- [ ] Add a new command / scheduled job to send /stats command / promo message to 146 chat

New feature idea:
- [ ] parse transaction amount from doc / screenshot and then add a new button "confirm (x) rub"
- bonus: test litellm

# New Tasks (March 7)
- [ ] Сделать предупреждение до оплаты о подтверждении регистрации
- [x] Добавить новый тип участника - организатор
- [x] Уведомлять о каждом сообщении CRM в валидационный чат (с полным детальным отчетом)
- [x] Добавить экспорт в Google Sheets с разделением по типам участников

# Рассылки (это потом сделаем)
- тем кто не оплатил
- тем кто оплатил но меньше чем нужно
- за пару дней до опрос "а ты придешь"
Идея по рассылкам:
1) сначала делаем спец-команду для админов (с фичой от botspot - visibility = admin only) - для ручного запуска
2) потом scheduled job для рассылок

Optional Improvements
- [ ] move early registration date to app settings
- [ ] for payment validation check - check screenshot message date, not current data, to determine if discount applies
- [ ] rework the database operations to return structured objects (to prevent future issues with missing fields)

# Scenario routes
- [ ] bugfix the multi-user payment flow. Currently there is some issues with the state management if multiple cities have multiple payment states and also maybe one of them gets cancelled.. it's a mess
- [ ]  не заканчивать регистрацию пока человек не подтвердил намерение оплатить
  - details: [payment_intent_validation.md](payment_intent_validation.md)

