from flask import Flask, render_template, request, redirect, flash as flask_flash, session
from pymongo import MongoClient
from bson import ObjectId
from bson.decimal128 import Decimal128
from passlib.hash import sha256_crypt
from dotenv import load_dotenv
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from urllib.parse import urlparse

load_dotenv()
app = Flask(__name__)
app.config["MONGO_URI"] = os.getenv("MONGOURI", "mongodb://localhost:27017/one_stop_shop")
app.config["SECRET_KEY"] = os.getenv("SECRETKEY") or os.urandom(32)
client = MongoClient(app.config["MONGO_URI"])
db = client.one_stop_shop
db.Products.create_index([("name", "text"), ("description", "text")])

def get_cart():
    if "user_id" not in session:
        session["user_id"] = str(db.Carts.insert_one({"cart": []}).inserted_id)
    cart = db.Carts.find_one({"_id": ObjectId(session["user_id"])})
    if cart is None:
        session["user_id"] = str(db.Carts.insert_one({"cart": []}).inserted_id)
        cart = {"cart": []}
    return cart["cart"]

def get_cart_count():
    return len(get_cart())

def normalize_price(value):
    if value is None:
        return 0.00
    if hasattr(value, "to_decimal"):
        return float(value.to_decimal().quantize(Decimal("0.01"), rounding = ROUND_HALF_UP))
    try:
        return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding = ROUND_HALF_UP))
    except (TypeError, ValueError, InvalidOperation):
        return 0.00

def normalize_cart_prices(cart):
    normalized = []
    for item in cart:
        item_copy = dict(item)
        item_copy["price"] = normalize_price(item_copy.get("price"))
        normalized.append(item_copy)
    return normalized

def normalize_products(products):
    normalized = []
    for product in products:
        product_copy = dict(product)
        product_copy["price"] = normalize_price(product_copy.get("price"))
        normalized.append(product_copy)
    return normalized

def safe_int(value, default = 0):
    try:
        n = int(value)
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default

def is_valid_image_url(value):
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

@app.route("/", methods = ["GET", "POST"])
def index():
    session.setdefault("user_id", str(db.Carts.insert_one({"cart": []}).inserted_id))
    search_query = request.args.get("search", "").strip()
    shop_filter = request.args.get("shop", "").strip()
    query = {}
    if search_query:
        query["$or"] = [
            {"name": {"$regex": re.escape(search_query), "$options": "i"}},
            {"description": {"$regex": re.escape(search_query), "$options": "i"}}
        ]
    if shop_filter:
        query["email"] = shop_filter
    try:
        products = normalize_products(list(db.Products.find(query).sort("name", 1)))
        shops = list(db.Shops.find().sort("shop_name", 1))
        shop_names = {shop["email"]: shop["shop_name"] for shop in shops}
        return render_template("index.html", 
                             shops = shops, 
                             products = products, 
                             shop_names = shop_names,
                             cart_count = get_cart_count(),
                             search_query = search_query,
                             shop_filter = shop_filter)
    except Exception as e:
        print(f"Search error: {e}")
        return render_template("index.html", 
                             shops = list(db.Shops.find().sort("shop_name", 1)), 
                             products = normalize_products(list(db.Products.find().sort("name", 1))),
                             shop_names = {},
                             cart_count = get_cart_count())

@app.route("/register", methods = ["GET", "POST"])
def register():
    if request.method == "POST" and request.form.get("form_id") == "register_form":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        owner_name = request.form.get("owner_name", "").strip()
        shop_name = request.form.get("shop_name", "").strip()
        contact = request.form.get("contact", "").strip()
        if not all([email, password, owner_name, shop_name, contact]):
            flash("Please complete all shop registration fields.")
            return redirect("/")
        if db.Shops.find_one({"email": email}):
            flash("That email is already registered.")
            return redirect("/")
        if db.Shops.find_one({"shop_name": shop_name}):
            flash("That shop name is already registered.")
            return redirect("/")
        try:
            db.Shops.insert_one({
                "email": email, 
                "password": sha256_crypt.hash(password), 
                "owner_name": owner_name, 
                "shop_name": shop_name, 
                "contact": contact
            })
            flash("Shop registered successfully.")
        except Exception as e:
            flash("An error occurred during registration. Please try again.")
            print(f"Registration error: {e}")
            return redirect("/")
        return redirect("/")
    return redirect("/")

@app.route("/owner_shop", methods = ["GET", "POST"])
def owner_shop():
    if "email" not in session:
        flash("You must first login.")
        return redirect("/")
    return render_template("owner_shop.html", products = normalize_products(list(db.Products.find({"email": session["email"]}).sort("name", 1))), name = session["name"])

@app.route("/shop_profile", methods = ["GET", "POST"])
def shop_profile():
    if "email" not in session:
        flash("You must first login.")
        return redirect("/")
    shop = db.Shops.find_one({"email": session["email"]})
    if not shop:
        session.clear()
        flash("Your shop account could not be found.")
        return redirect("/")
    if request.method == "POST":
        owner_name = request.form.get("owner_name", "").strip()
        shop_name = request.form.get("shop_name", "").strip()
        contact = request.form.get("contact", "").strip()
        if not all([owner_name, shop_name, contact]):
            flash("Please complete all shop profile fields.")
            return render_template("shop_profile.html", shop = shop)
        duplicate = db.Shops.find_one({"shop_name": shop_name, "email": {"$ne": session["email"]}})
        if duplicate:
            flash("That shop name is already registered.")
            return render_template("shop_profile.html", shop = shop)
        db.Shops.update_one(
            {"email": session["email"]},
            {"$set": {"owner_name": owner_name, "shop_name": shop_name, "contact": contact}}
        )
        session["name"] = owner_name
        flash("Shop profile updated successfully.")
        return redirect("/owner_shop")
    return render_template("shop_profile.html", shop = shop)

@app.route("/login", methods = ["GET", "POST"])
def login():
    if request.method == "POST" and request.form.get("form_id") == "login_form":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        if not email or not password:
            flash("Email and password are required.")
            return redirect("/")
        try:
            shop = db.Shops.find_one({"email": email})
            if not shop:
                flash("Email is not registered to any shop.")
                return redirect("/")
            elif sha256_crypt.verify(password, shop["password"]):
                session["email"] = shop["email"]
                session["name"] = shop["owner_name"]
                flash("Login successful.")
                return redirect("/owner_shop")
            flash("Password is incorrect.")
        except Exception as e:
            flash("An error occurred during login. Please try again.")
            print(f"Login error: {e}")
        return redirect("/")
    return redirect("/")

@app.route("/logout", methods = ["GET", "POST"])
def logout():
    session.clear()
    flash("Logout successful.")
    return redirect("/")

@app.route("/add_product", methods = ["POST"])
def add_product():
    if "email" not in session:
        flash("Please login before adding products.")
        return redirect("/")
    if request.form.get("form_id") == "add_product_form":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        price = request.form.get("price", "").strip()
        quantity = safe_int(request.form.get("quantity"), 0)
        image_link = request.form.get("link", "").strip()
        if not all([name, description, image_link]) or not is_valid_image_url(image_link):
            flash("Please provide product name, description, and image link.")
            return redirect("/owner_shop")
        try:
            price_value = Decimal(price).quantize(Decimal("0.01"), rounding = ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            price_value = None
        if price_value is None or price_value.to_decimal() < 0:
            flash("Price must be a positive number.")
            return redirect("/owner_shop")
        if quantity <= 0:
            flash("Quantity must be at least 1.")
            return redirect("/owner_shop")
        if len(name) > 100:
            flash("Product name is too long (max 100 characters).")
            return redirect("/owner_shop")
        try:
            db.Products.insert_one({
                "name": name, 
                "description": description, 
                "price": price_value, 
                "quantity": quantity, 
                "link": image_link, 
                "email": session["email"]
            })
            flash("Product added successfully.")
        except Exception as e:
            print(f"Add product error: {e}")
            flash("Error adding product. Please try again.")
        return redirect("/owner_shop")
    return redirect("/owner_shop")

@app.route("/edit_product/<id>", methods = ["GET", "POST"])
def edit_product(id):
    if "email" not in session:
        flash("Please login before editing products.")
        return redirect("/")
    try:
        product = db.Products.find_one({"_id": ObjectId(id), "email": session["email"]})
    except Exception:
        product = None
    if not product:
        flash("Product not found or you do not own it.")
        return redirect("/owner_shop")
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        description = request.form.get("description", "").strip()
        price = request.form.get("price", "").strip()
        image_link = request.form.get("link", "").strip()
        if not all([name, description, image_link]) or not is_valid_image_url(image_link):
            flash("Please provide a valid name, description, and image URL.")
            return render_template("edit_product.html", product = product)
        try:
            price_value = Decimal(price).quantize(Decimal("0.01"), rounding = ROUND_HALF_UP)
            if price_value < 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            flash("Price must be a positive number.")
            return render_template("edit_product.html", product = product)
        if len(name) > 100:
            flash("Product name is too long (max 100 characters).")
            return render_template("edit_product.html", product = product)
        db.Products.update_one(
            {"_id": product["_id"], "email": session["email"]},
            {"$set": {"name": name, "description": description, "price": Decimal128(price_value), "link": image_link}}
        )
        flash("Product updated successfully.")
        return redirect("/owner_shop")
    return render_template("edit_product.html", product = product)

@app.route("/add_stock/<id>", methods = ["POST"])
def add_stock(id):
    if "email" not in session:
        flash("You must be logged in as a shop owner.")
        return redirect("/")
    try:
        product = db.Products.find_one({"_id": ObjectId(id)})
        if not product:
            flash("Product not found.")
            return redirect("/owner_shop")
        if product["email"] != session["email"]:
            flash("You can only manage your own products.")
            return redirect("/owner_shop")
        quantity = safe_int(request.form.get("quantity"), 0)
        if quantity <= 0:
            flash("Please enter a valid quantity to add.")
            return redirect("/owner_shop")
        db.Products.update_one({"_id": ObjectId(id)}, {"$inc": {"quantity": quantity}})
        flash(f"Successfully added {quantity} {product['name']}(s) to stock.")
    except Exception as e:
        print(f"Add stock error: {e}")
        flash("Error adding stock.")
    return redirect("/owner_shop")

@app.route("/delete/<id>", methods = ["POST"])
def delete(id):
    if "email" not in session:
        flash("Please login to manage your products.")
        return redirect("/")
    try:
        product = db.Products.find_one({"_id": ObjectId(id)})
        if not product:
            flash("Product not found.")
            return redirect("/owner_shop")
        if product["email"] != session["email"]:
            flash("You can only delete your own products.")
            return redirect("/owner_shop")
        db.Products.delete_one({"_id": ObjectId(id)})
        flash("Product deleted successfully.")
    except Exception as e:
        print(f"Delete error: {e}")
        flash("Error deleting product.")
    return redirect("/owner_shop")

@app.route("/view_shop/<email>", methods = ["GET"])
@app.route("/shop/<email>", methods = ["GET"])
def view_shop(email):
    shop = db.Shops.find_one({"email": email})
    if not shop:
        flash("That shop could not be found.")
        return redirect("/")
    return render_template("customer_shop.html", products = normalize_products(list(db.Products.find({"email": email}).sort("name", 1))), cart_count = get_cart_count(), email = email, shop = shop)

def add_to_cart(product_id, redirect_target):
    quantity = safe_int(request.form.get("quantity"), 0)
    if quantity <= 0:
        flash("Please enter a valid quantity.")
        return redirect(redirect_target)
    try:
        object_id = ObjectId(product_id)
        product = db.Products.find_one({"_id": object_id})
        if not product:
            flash("This item is no longer available.")
            return redirect(redirect_target)
        stock_update = db.Products.update_one(
            {"_id": object_id, "quantity": {"$gte": quantity}},
            {"$inc": {"quantity": -quantity}}
        )
        if stock_update.modified_count != 1:
            flash(f"Only {product['quantity']} {product['name']}(s) are available in stock.")
            return redirect(redirect_target)
        cart = get_cart()
        found = False
        for item in cart:
            if item["product_id"] == str(product["_id"]):
                item["quantity"] += quantity
                found = True
                break
        if not found:
            cart.append({"product_id": str(product["_id"]), "name": product["name"], "quantity": quantity, "price": product["price"]})
        db.Carts.update_one({"_id": ObjectId(session["user_id"])}, {"$set": {"cart": cart}})
        flash(f"Successfully added {quantity} {product['name']}(s) to your cart.")
    except Exception as e:
        print(f"Add to cart error: {e}")
        flash("Error adding item to cart.")
    return redirect(redirect_target)

@app.route("/add_cart_home/<id>", methods = ["POST"])
def add_cart_home(id):
    return add_to_cart(id, "/")

@app.route("/add_cart_shop/<id>/<email>", methods = ["POST"])
def add_cart_shop(id, email):
    return add_to_cart(id, f"/shop/{email}")

@app.route("/remove_from_cart/<product_id>", methods = ["POST"])
def remove_from_cart(product_id):
    if "user_id" not in session:
        flash("Your session has expired.")
        return redirect("/")
    try:
        cart = get_cart()
        removed = next((item for item in cart if item["product_id"] == product_id), None)
        if not removed:
            flash("That cart item could not be found.")
            return redirect("/view_cart")
        cart[:] = [item for item in cart if item["product_id"] != product_id]
        db.Products.update_one({"_id": ObjectId(product_id)}, {"$inc": {"quantity": removed["quantity"]}})
        db.Carts.update_one({"_id": ObjectId(session["user_id"])}, {"$set": {"cart": cart}})
        flash(f"Removed {removed['name']} from cart.")
    except Exception as e:
        print(f"Remove from cart error: {e}")
        flash("Error removing item from cart.")
    return redirect("/view_cart")

@app.route("/update_cart_quantity", methods = ["POST"])
def update_cart_quantity():
    if "user_id" not in session:
        flash("Your session has expired.")
        return redirect("/")
    try:
        product_id = request.form.get("product_id", "").strip()
        new_quantity = safe_int(request.form.get("quantity"), 0)
        if not product_id or new_quantity <= 0:
            flash("Invalid quantity.")
            return redirect("/view_cart")
        cart = get_cart()
        for item in cart:
            if item["product_id"] == product_id:
                old_quantity = item["quantity"]
                difference = new_quantity - old_quantity
                if difference > 0:
                    stock_update = db.Products.update_one(
                        {"_id": ObjectId(product_id), "quantity": {"$gte": difference}},
                        {"$inc": {"quantity": -difference}}
                    )
                    if stock_update.modified_count != 1:
                        flash("There is not enough stock for that quantity.")
                        return redirect("/view_cart")
                elif difference < 0:
                    db.Products.update_one({"_id": ObjectId(product_id)}, {"$inc": {"quantity": -difference}})
                item["quantity"] = new_quantity
                break
        db.Carts.update_one({"_id": ObjectId(session["user_id"])}, {"$set": {"cart": cart}})
        flash("Cart updated successfully.")
    except Exception as e:
        print(f"Update cart error: {e}")
        flash("Error updating cart.")
    return redirect("/view_cart")

@app.route("/view_cart", methods = ["GET", "POST"])
def view_cart():
    cart = normalize_cart_prices(get_cart())
    total = sum(item["quantity"] * item["price"] for item in cart)
    return render_template("checkout.html", cart = cart, total = total)

@app.route("/checkout", methods = ["POST"])
def checkout():
    try:
        if "user_id" in session:
            cart = get_cart()
            if not cart:
                flash("Your cart is empty.")
                return redirect("/view_cart")
            db.Carts.delete_one({"_id": ObjectId(session["user_id"])})
            session.pop("user_id", None)
            session.pop("cart", None)
            flash("Thank you for shopping at One Stop Shop! Your order has been placed.")
    except Exception as e:
        print(f"Checkout error: {e}")
        flash("An error occurred during checkout. Please try again.")
    return redirect("/")

def flash(message, category=None):
    if category is None:
        text = str(message).lower()
        if any(word in text for word in (
            "error", "failed", "invalid", "not found", "cannot", "not registered",
            "required", "must", "already", "not available", "please", "incorrect"
        )):
            category = "danger"
        elif any(word in text for word in (
            "success", "successfully", "registered", "added", "deleted",
            "updated", "placed", "thank you"
        )):
            category = "success"
        else:
            category = "neutral"
    flask_flash(message, category)

# if __name__ == "__main__":
#     app.run(debug = True)