# Карта функций и аудит UX бота

Инвентаризация обработчиков по исходному коду. Наличие функции в списке не означает проверку её выполнения в Telegram.

## Проверенные сценарии и изменения

- Пополнение: верхний лимит берётся из конфигурации метода оплаты вместо отдельного жёстко заданного значения.
- Если способы оплаты отключены, добавлен прямой переход в поддержку.
- Рефералы: добавлены нативное копирование ссылки и открытие выбора получателя в Telegram. Отправку выполняет пользователь.
- Профиль: динамическое имя экранируется для HTML.

## Следующие направления проверки

- Покупка и выдача: истечение предложения, конкурентная покупка последнего товара, повторный callback, отзыв доступа.
- Платежи: повторные webhook, задержка подтверждения, недоступность провайдера, соответствие лимитов во всех интерфейсах.
- Поддержка: сохранение контекста заказа, вложения и возврат к предыдущему экрану.
- Бонусы и рефералы: дневные лимиты, повторные начисления и разделение внесённых и бонусных средств.
- Админка: массовые операции, частичные ошибки, восстановление после перезапуска.
- Партнёрские магазины: изоляция данных, баланс и настройки каждого партнёра.

## Инвентаризация

### handlers/admin/add_account.py

`cancel_add_account`, `start_add_account_session`, `start_add_account`, `execute_send_code`, `process_session_file`, `process_phone`, `process_code`, `process_2fa`, `process_price`, `process_category_text_input`, `process_category_selection`, `finalize_imported_session`, `finalize_and_save_account`

### handlers/admin/admin_panel.py

`tg_emoji`, `is_admin`, `admin_start`, `admin_home`, `admin_category`, `show_stats`, `show_users`, `admin_maintenance_handler`, `check_maintenance_from_admin`, `admin_balance_menu_handler`, `admin_balance_step_1`, `admin_balance_step_2`, `admin_balance_step_3`, `show_prices_menu`, `start_change_price`, `process_new_price`, `show_promos_menu`, `list_promos`, `process_delete_promo`, `show_accounts_list_first_page`, `show_accounts_list_page`, `show_accounts_page`, `show_account_detail`, `direct_get_code_from_card`, `ask_delete_account`, `confirm_delete_account`, `edit_price_ask`, `edit_price_save`, `edit_country_ask`, `edit_country_pick`, `admin_settings_menu_handler`, `admin_edit_setting_handler`, `admin_save_support`, `admin_save_reviews`, `admin_save_tonkeeper`, `admin_sub_menu_handler`, `admin_sub_toggle_handler`, `admin_sub_clear_handler`, `admin_sub_set_handler`, `admin_sub_process_channel`, `market_report`

### handlers/admin/advertising.py

`helper_keyboard`, `helper_entry`, `manage_helper`, `helper_list`, `advertising_action`, `advertising_name`

### handlers/admin/broadcast.py

`is_admin`, `_markup_from_spec`, `recipients`, `broadcast_start`, `broadcast_got_content`, `broadcast_preview`, `stop_broadcast`, `broadcast_run`

### handlers/admin/button_editor.py

`is_admin`, `btn_editor_categories`, `btn_editor_list`, `btn_edit_action`, `btn_start_set_label`, `btn_process_label`, `btn_start_set_emoji`, `btn_process_emoji`, `btn_clear_emoji`, `btn_edit_welcome_photo`, `btn_process_welcome_photo`, `btn_process_welcome_photo_invalid`

### handlers/admin/category_manager.py

`slugify`, `is_admin`, `categories_list`, `category_detail`, `category_toggle`, `category_delete`, `category_add_account`, `category_create_name`, `category_create_name_process`, `category_create_emoji_process`, `category_edit_name`, `category_edit_name_process`, `category_edit_emoji`, `category_edit_emoji_process`

### handlers/admin/demo.py

`button`, `demo`

### handlers/admin/manage.py

`is_admin`, `cancel_manage_action`, `start_add_regular`, `process_add_regular`, `start_del_account`, `confirm_delete_account`, `start_promo`, `process_promo`

### handlers/admin/referrals.py

`menu`, `text`, `show`, `choose`, `save`, `show_blocks`, `choose_block`, `save_block`, `render_invited`, `lookup`, `lookup_id`, `lookup_page`

### handlers/admin/refunds.py

`back_to_order`, `start_refund`, `refund_reason`, `confirm_refund`

### handlers/admin/sbp.py

`render`, `show`, `toggle`

### handlers/admin/shop_control.py

`button`, `back`, `show_shop_control`, `preview_maintenance`, `toggle_mode`, `notice_entry`, `notice_save`, `review_list`, `review_entry`, `review_reason`, `review_confirm`

### handlers/admin/spam_checks.py

`button`, `all_accounts`, `one_account`, `audit_sessions`

### handlers/admin/tools.py

`search_menu`, `open_search`, `start_search`, `user_card`, `order_card`, `order_menu`, `search_user`, `search_order`, `open_order`, `audit_line`, `show_audit`

### handlers/direct_support.py

`cancel_keyboard`, `reply_keyboard`, `copyable`, `begin`, `support_command`, `support`, `purchase_help`, `legacy_support`, `end_support`, `relay`, `user_message`, `begin_reply`, `admin_message`

### handlers/expansion.py

`help_admin`, `prepare`, `confirm`, `approve`, `tools_menu`, `refund_queue`

### handlers/navigation.py

`cancel`, `page_info`, `stale_button`, `unknown_message`, `unexpected_error`

### handlers/partners.py

`kb`, `is_root`, `own`, `main_username`, `show_funding`, `request_entry`, `partner_admin`, `partner_admin_button`, `partner_actions`, `receive_token`, `receive_ban`, `edit_content`, `receive_content`, `funding_entry`, `fund_action`, `receive_amount`

### handlers/quality.py

`back`, `identifier`, `begin_review`, `submit_review`, `begin_warranty`, `submit_warranty`, `begin_features`, `submit_features`, `begin_discount`, `submit_discount`, `removed_activity`, `show_reviews`

### handlers/tickets.py

`identifier`, `button`, `order_back`, `notify`, `display_ticket`, `purchase_help`, `open_ticket`, `start_reply`, `submit_ticket`, `submit_reply`, `close_ticket`, `show_inbox`, `view_photo`

### handlers/user/balance.py

`button`, `show_balance`, `back_to_main`, `topup_balance_menu`, `_start_deposit`, `deposit_entry`, `process_lave_amount`, `check_payment`, `sbp_confirmation`, `sbp_buttons`, `confirm_sbp`

### handlers/user/language.py

`language_menu`, `language_command`, `choose_language`, `save_language`

### handlers/user/profile.py

`user_settings`, `user_rules`, `my_profile`, `referral_info`, `invited_users`

### handlers/user/promo.py

`ask_promo`, `cancel_promo`, `process_promo`

### handlers/user/purchases.py

`button`, `my_purchases`, `render_order`, `open_purchase`, `complete_purchase`, `confirm_completion`

### handlers/user/restock.py

`category_key`, `render_subscriptions`, `show_subscriptions`, `change_subscription`

### handlers/user/rewards.py

`wheel`

### handlers/user/shop.py

`button`, `open_shop`, `select_product`, `show_product`, `select_specific_account`, `confirm_purchase`, `deliver_login_code`, `ask_purchase_promo`, `enter_purchase_promo`, `all_categories`, `department`

### handlers/user/shop_navigation.py

`btn`, `kb`, `price`, `country_label`, `context`, `release`, `clear`, `entry`, `free_account`, `show_countries`, `show_years`, `show_products`, `quantity_screen`, `quote_bulk`, `pay_bulk`, `navigate`, `message_call`, `search`, `custom_quantity`

### handlers/user/stars.py

`pre_checkout`, `receipt`, `entry`, `native`, `preset`, `count`, `support`

### handlers/user/start.py

`cmd_start`, `callback_back_main`, `show_info`, `check_sub_status_callback`
