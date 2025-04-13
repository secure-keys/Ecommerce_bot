from flask import Flask, request
from telegram import Update, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, InlineQueryHandler, CallbackQueryHandler, MessageHandler, Filters, CallbackContext
import database
import os
import re
import sqlite3

app = Flask(__name__)
TOKEN = "7679035280:AAEDbzms9ijscpyfuCG0Rr49gzbQKm2baBo"  # @Shopenibelbot
MERCHANT_ID = 6613592916  # Your Telegram user ID
updater = Updater(TOKEN, use_context=True)
dp = updater.dispatcher

# Initialize database
database.init_db()

# Command to add product (for owner)
def add_product(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if user_id != MERCHANT_ID:
        update.message.reply_text("Unauthorized!")
        return
    context.user_data['adding_product'] = True
    context.user_data['product_data'] = {}
    update.message.reply_text("Enter product name:")

# Command to remove product (for owner)
def remove_product(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    if user_id != MERCHANT_ID:
        update.message.reply_text("Unauthorized!")
        return
    if not context.args:
        update.message.reply_text("Please provide the SKU to remove (e.g., /removeproduct CHV-001)")
        return
    sku = context.args[0]
    name = database.remove_product(sku)
    if name:
        update.message.reply_text(f"Product '{name}' (SKU: {sku}) removed successfully!")
    else:
        update.message.reply_text(f"Product with SKU '{sku}' not found!")

# Handle text/photo messages
def handle_message(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id
    text = update.message.text.lower() if update.message.text else None

    # Product addition
    if context.user_data.get('adding_product'):
        user_data = context.user_data['product_data']
        if update.message.photo:
            photo = update.message.photo[-1].get_file()
            image_path = f"images/{user_data['sku']}.jpg"
            os.makedirs('images', exist_ok=True)
            photo.download(image_path)
            database.add_product(
                user_data['name'], user_data['sku'],
                user_data['colour_flavour'], user_data['price'], image_path
            )
            update.message.reply_text("Product added!")
            context.user_data.clear()
        else:
            text = update.message.text
            if 'name' not in user_data:
                user_data['name'] = text
                update.message.reply_text("Enter SKU:")
            elif 'sku' not in user_data:
                user_data['sku'] = text
                update.message.reply_text("Enter colour/flavour:")
            elif 'colour_flavour' not in user_data:
                user_data['colour_flavour'] = text
                update.message.reply_text("Enter price (in ₦):")
            elif 'price' not in user_data:
                try:
                    user_data['price'] = float(text)
                    update.message.reply_text("Upload product image:")
                except ValueError:
                    update.message.reply_text("Invalid price! Enter a number:")

    # Awaiting quantity input after "Add to Cart"
    elif context.user_data.get('awaiting_quantity'):
        if not text:
            update.message.reply_text("Please enter a number (e.g., 2).")
            return
        try:
            quantity = int(text)
            if quantity <= 0:
                update.message.reply_text("Please enter a valid number greater than 0 (e.g., 2).")
                return
            sku = context.user_data['awaiting_quantity']['sku']
            name = context.user_data['awaiting_quantity']['name']
            print(f"Adding {quantity} units of SKU {sku} for user {user_id}")
            database.toggle_cart(user_id, sku, add=True, quantity=quantity)
            update.message.reply_text(f"Added {quantity} units of {name} to your cart!")
            # Add buttons for next steps
            keyboard = [
                [InlineKeyboardButton("View Cart", callback_data="view_cart")],
                [InlineKeyboardButton("Continue Shopping", callback_data="continue")]
            ]
            context.bot.send_message(
                chat_id,
                "What would you like to do next?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            # Refresh the inline search dropdown if this was triggered from an inline query
            if update.inline_query:
                print(f"Refreshing inline query after quantity confirmation for user {user_id}")
                inline_query(update, context)
            context.user_data.clear()
        except ValueError:
            update.message.reply_text("Please enter a valid number greater than 0 (e.g., 2).")

    # Proof of payment
    elif context.user_data.get('awaiting_proof'):
        if update.message.photo:
            photo = update.message.photo[-1].get_file()
            proof_path = f"proof/{user_id}_{context.user_data['order_id']}.jpg"
            os.makedirs('proof', exist_ok=True)
            photo.download(proof_path)
            order_id = context.user_data['order_id']
            items = context.user_data['order_items']
            total = context.user_data['order_total']
            username = update.message.from_user.username or "No username"
            updater.bot.send_message(
                MERCHANT_ID,
                f"New Order #{order_id}\nUser: {username} (ID: {user_id})\nItems:\n" +
                "\n".join([f"- {name} ({sku}) x{qty}: ₦{price*qty:.2f}" for name, sku, _, price, qty, _ in items]) +
                f"\nTotal: ₦{total:.2f}\nProof of payment received.",
                parse_mode='HTML'
            )
            updater.bot.send_photo(MERCHANT_ID, open(proof_path, 'rb'))
            update.message.reply_text(
                "Proof received! Your order has been recorded successfully and is being processed. "
                "Please message @ShopWithEnibel with your delivery details."
            )
            context.user_data.clear()
        else:
            update.message.reply_text("Please upload an image as proof of payment.")

    # Cart removal
    elif context.user_data.get('viewing_cart') and text and text.startswith("remove "):
        match = re.match(r'remove (\d+)', text.lower())
        if match:
            index = int(match.group(1))
            if database.remove_cart_item_by_index(user_id, index):
                update.message.reply_text(f"Item {index} removed!")
                view_cart(user_id, chat_id, context)
            else:
                update.message.reply_text("Invalid serial number!")
        else:
            update.message.reply_text("Use format: remove <b>serial number</b> (e.g., remove 1)")

# Inline search with cart toggling
def inline_query(update: Update, context: CallbackContext):
    query = update.inline_query.query
    user_id = update.inline_query.from_user.id
    print(f"Inline query received: '{query}' from user {user_id}")
    if not query:
        print("Query is empty, returning early")
        return
    results = database.search_products(query, user_id)
    print(f"Found {len(results)} products for query '{query}': {results}")
    answers = []
    for name, sku, colour_flavour, price, image_path, in_cart in results:
        print(f"Processing product: {name} (SKU: {sku})")
        button = InlineKeyboardButton(
            text=f"{'✅ Remove from' if in_cart else 'Add to'} Cart",
            callback_data=f"cart_{sku}_{'remove' if in_cart else 'add'}"
        )
        answers.append(
            InlineQueryResultArticle(
                id=sku,
                title=name,
                description=f"{colour_flavour} | ₦{price:.2f}",
                input_message_content=InputTextMessageContent(
                    f"{name} | {sku} | {colour_flavour} | ₦{price:.2f}"
                ),
                reply_markup=InlineKeyboardMarkup([[button], [InlineKeyboardButton("View Cart", callback_data="view_cart")]])
            )
        )
    print(f"Sending {len(answers)} answers to Telegram")
    try:
        update.inline_query.answer(answers)
        print("Successfully sent answers")
    except Exception as e:
        print(f"Failed to send answers: {e}")

# View cart command
def view_cart_command(update: Update, context: CallbackContext):
    view_cart(update.message.from_user.id, update.message.chat_id, context)

# Handle button clicks
def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id if query.message else query.from_user.id
    data = query.data

    if data.startswith("cart_"):
        _, sku, action = data.split("_")
        add = action == "add"
        if add:
            # Get product name for the prompt
            conn = sqlite3.connect('products.db')
            cursor = conn.cursor()
            cursor.execute('SELECT name FROM products WHERE sku = ?', (sku,))
            product = cursor.fetchone()
            conn.close()
            if product:
                name = product[0]
                # Add to cart with default quantity 1 (will be updated after user input)
                database.toggle_cart(user_id, sku, add=True, quantity=1)
                # Prompt for quantity
                context.user_data['awaiting_quantity'] = {'sku': sku, 'name': name}
                context.bot.send_message(
                    chat_id,
                    f"How many units of {name} do you want to purchase? Reply with a number (e.g., 2)."
                )
                query.answer("Please specify the quantity.")
            else:
                query.answer("Product not found!")
        else:
            print(f"Removing item with SKU {sku} for user {user_id}")
            database.toggle_cart(user_id, sku, add=False)
            query.answer("Item removed from cart!")
        # Refresh the inline search dropdown if this is an inline query
        if update.inline_query:
            print(f"Refreshing inline query for user {user_id}")
            inline_query(update, context)
    elif data == "view_cart":
        print(f"View Cart button clicked by user {user_id} in chat {chat_id}")
        view_cart(user_id, chat_id, context, query)
    elif data == "pay":
        keyboard = [
            [InlineKeyboardButton("Interswitch (Card)", callback_data="pay_interswitch")],
            [InlineKeyboardButton("Bank Transfer", callback_data="pay_bank")],
            [InlineKeyboardButton("Continue Shopping", callback_data="continue")]
        ]
        if query.message:
            query.message.edit_text("Choose payment method:", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            context.bot.send_message(chat_id, "Choose payment method:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "pay_interswitch":
        items = database.get_cart(user_id)
        if not items:
            query.answer("Cart is empty!")
            return
        total = sum(price * qty for _, _, _, price, qty, _ in items)
        payment_url = "https://interswitch.payment.url"  # Placeholder
        keyboard = [
            [InlineKeyboardButton("Pay Now", url=payment_url)],
            [InlineKeyboardButton("Continue Shopping", callback_data="continue")]
        ]
        if query.message:
            query.message.edit_text(
                f"Total: <b>₦{total:.2f}</b>\nProceed to Interswitch payment:",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            context.bot.send_message(
                chat_id,
                f"Total: <b>₦{total:.2f}</b>\nProceed to Interswitch payment:",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        username = query.from_user.username or "No username"
        order_id = database.create_order(user_id, username, total, [(sku, qty, price) for _, sku, _, price, qty, _ in items])
        updater.bot.send_message(
            MERCHANT_ID,
            f"New Order #{order_id}\nUser: {username} (ID: {user_id})\nItems:\n" +
            "\n".join([f"- {name} ({sku}) x{qty}: ₦{price*qty:.2f}" for name, sku, _, price, qty, _ in items]) +
            f"\nTotal: ₦{total:.2f}\nPaid via Interswitch (pending confirmation).",
            parse_mode='HTML'
        )
    elif data == "pay_bank":
        items = database.get_cart(user_id)
        if not items:
            query.answer("Cart is empty!")
            return
        total = sum(price * qty for _, _, _, price, qty, _ in items)
        keyboard = [[InlineKeyboardButton("Continue Shopping", callback_data="continue")]]
        if query.message:
            query.message.edit_text(
                f"Total: <b>₦{total:.2f}</b>\nPlease transfer to:\n"
                "Account Number: 9025259913\nName: Blessing Eniye\nBank: Moniepoint\n\n"
                "Reply with proof of payment (image):",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            context.bot.send_message(
                chat_id,
                f"Total: <b>₦{total:.2f}</b>\nPlease transfer to:\n"
                "Account Number: 6433846001\nName: Babel Consult\nBank: Moniepoint\n\n"
                "Reply with proof of payment (image):",
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        context.user_data['awaiting_proof'] = True
        context.user_data['order_items'] = items
        context.user_data['order_total'] = total
        context.user_data['order_id'] = database.create_order(
            user_id, query.from_user.username or "No username", total,
            [(sku, qty, price) for _, sku, _, price, qty, _ in items]
        )
    elif data == "continue":
        if query.message:
            query.message.delete()
        context.bot.send_message(chat_id, "Search for more products with @shopenibelbot or use /cart to view cart.")

# View cart logic
def view_cart(user_id, chat_id, context, query=None):
    items = database.get_cart(user_id)
    context.user_data['viewing_cart'] = True
    if not items:
        text = "Your cart is empty!"
        keyboard = [[InlineKeyboardButton("Continue Shopping", callback_data="continue")]]
    else:
        total = sum(price * qty for _, _, _, price, qty, _ in items)
        text = "Your Cart:\n" + "\n".join(
            [f"{i+1}. {name} ({sku}) - {colour_flavour} | ₦{price:.2f} x{qty}" for i, (name, sku, colour_flavour, price, qty, _) in enumerate(items)]
        ) + f"\n\n<b>Total: ₦{total:.2f}</b>\nTo remove an item, reply: remove <b>serial number</b> (e.g., remove 1)"
        keyboard = [
            [InlineKeyboardButton("Pay", callback_data="pay")],
            [InlineKeyboardButton("Continue Shopping", callback_data="continue")]
        ]
    print(f"Sending cart message for user {user_id}: {text}")
    if query and query.message:
        query.message.edit_text(text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        context.bot.send_message(chat_id, text, parse_mode='HTML', reply_markup=InlineKeyboardMarkup(keyboard))

# Set up handlers
dp.add_handler(CommandHandler("addproduct", add_product))
dp.add_handler(CommandHandler("removeproduct", remove_product))
dp.add_handler(CommandHandler("cart", view_cart_command))
dp.add_handler(InlineQueryHandler(inline_query))
dp.add_handler(CallbackQueryHandler(button_handler))
dp.add_handler(MessageHandler(Filters.text & ~Filters.command | Filters.photo, handle_message))

# Flask route for webhook
@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(force=True), updater.bot)
    dp.process_update(update)
    return 'OK'

if __name__ == '__main__':
    updater.start_webhook(listen="0.0.0.0", port=5000, url_path=TOKEN)
updater.bot.set_webhook(f"https://your-app-name.herokuapp.com/{TOKEN}")
app.run(host="0.0.0.0", port=5000)