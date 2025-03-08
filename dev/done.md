# Done
- [x] add a new 'simple stats' command
- [x] and include it as a button to admin flow
- [x] add unit tests

- [x] Улучшить сообщение о подтверждении оплаты, чтобы там не id было
- [x] Поменять чтобы для старых выпусков (у кого большие суммы получаются) было 3000 обязательно и по формуле рекомендовано
- [x] Пофиксить сценарий что "друзьям школы" 0

- [x] add a test stand
  - dev branch?
  - new bot token - done
- [x] Add the payment status info to the /stats command

- [x] make sure to save reg,min and formula amounts to database
- [x] export payment amounts to google sheet

- [x] Fix "I will pay later" route of the start menu -> currently there's no way to manage registrations now from unpaid state
- [x] auto export to google sheets on each registration
- [x] add new command /cancel_registration
- [x] hide the admin-only commands from menu (use botspot visibility). Print the admin-only commands in start menu for admins
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

- [x]  Новая кнопка "я не выпускник". И кнопка "я учитель". Если учитель - то бесплатно. Как для Питера. Ну и сохранить это надо.
  thoughts on scenarios
- Новая кнопка "я не выпускник" должна быть там же где ты вводишь год выпуска из школы. Чтобы если ты не можешь его ввести - у тебя был выход
- Но непонятно какой дальше сценарий - какая сумма платежа? Можно просто рекомендованную ставить
- Пермь - 2500, Москва - 5000