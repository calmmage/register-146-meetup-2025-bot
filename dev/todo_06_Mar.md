- [ ] add a new 'simple stats' command
- [ ] and include it as a button to admin flow
- [ ] add unit tests

# Promo
- [ ] Add a new command / scheduled job to send /stats command / promo message to 146 chat

New feature idea:
- parse transaction amount from doc / screenshot and then add a new button "confirm (x) rub"
- bonus: test litellm

# New Tasks (March 7)
- [ ] Сделать предупреждение до оплаты о подтверждении регистрации

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

