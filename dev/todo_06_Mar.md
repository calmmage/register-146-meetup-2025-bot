Scenario routes
- [ ] Fix "I will pay later" routo of the start menu -> there's no way to manage registrations now from unpaid state
- [ ]  не заканчивать регистрацию пока человек не подтвердил намерение оплатить
- [ ]  Новая кнопка "я не выпускник"

Todo
- [ ] auto export to google sheets on each registration

Promo
- [ ] Add the payment status info to the /stats command
- [ ] Add a new command / scheduled job to send /stats command / promo message to 146 chat

Commands
- [ ] hide the admin-only commands from menu (use botspot visibility). Print the admin-only commands in start menu for admins
- [ ] add new command /cancel_registration

Optional Improvements
- [ ] move early registration date to app settings
- [ ] for payment validation check - check screenshot message date, not current data, to determine if discount applies

Done
- [x] Экспортировать инфо о платежах в CSV и sheets
- [x] Добавить поддержку платежей файлом pdf. Просто так же форвардить
- [x] указывать в сообщении для валидации правильную сумму к оплате
- [x] После 15 марта не показывать минимальную сумму со скидкой
- [x] Переписать сообщение о скидке:
- "при ранней регистрации" -> "при ранней оплате"
- "15.03.25" -> 15 марта
- 2800 -> 2800 руб
- [x]  в букву класс не давать длиннее 1 буквы
- [x] после/при валидации вычислять и писать человеку если его взнос меньше рекомендуемой суммы


Рассылки (это потом сделаем)
- тем кто не оплатил
- тем кто оплатил но меньше чем нужно
- за пару дней до опрос "а ты придешь"

Идея:
1) сначала делаем спец-команду для админов (с фичой от botspot - visibility = admin only) - для ручного запуска
2) потом scheduled job для рассылок