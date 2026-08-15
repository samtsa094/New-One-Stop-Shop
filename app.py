from flask import Flask, render_template, request, redirect, flash, session
from pymongo import MongoClient
from bson import ObjectId
from passlib.hash import sha256_crypt
from dotenv import load_dotenv
import os

load_dotenv()
app = Flask(__name__)
app.config["MONGO_URI"] = os.getenv("MONGOURI", "mongodb://localhost:27017/one_stop_shop")
app.config["SECRET_KEY"] = os.getenv("SECRETKEY", "dev-secret-key")
client = MongoClient(app.config["MONGO_URI"])
db = client.one_stop_shop

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

def safe_int(value, default = 0):
    try:
        n = int(value)
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default

@app.route("/", methods = ["GET", "POST"])
def index():
    session.setdefault("user_id", str(db.Carts.insert_one({"cart": []}).inserted_id))
    search_query = request.args.get("search", "").strip()
    shop_filter = request.args.get("shop", "").strip()
    query = {}
    if search_query:
        query["$text"] = {"$search": search_query}
    if shop_filter:
        query["email"] = shop_filter
    try:
        if search_query and "$text" not in query:
            query["$or"] = [
                {"name": {"$regex": search_query, "$options": "i"}},
                {"description": {"$regex": search_query, "$options": "i"}}
            ]
        products = list(db.Products.find(query).sort("name", 1))
        shops = list(db.Shops.find().sort("shop_name", 1))
        return render_template("index.html", 
                             shops=shops, 
                             products=products, 
                             cart_count=get_cart_count(),
                             search_query=search_query,
                             shop_filter=shop_filter)
    except Exception as e:
        print(f"Search error: {e}")
        return render_template("index.html", 
                             shops=list(db.Shops.find().sort("shop_name", 1)), 
                             products=list(db.Products.find().sort("name", 1)), 
                             cart_count=get_cart_count())

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
    return render_template("owner_shop.html", products = list(db.Products.find({"email": session["email"]}).sort("name", 1)), name = session["name"])

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
            if shop and sha256_crypt.verify(password, shop["password"]):
                session["email"] = shop["email"]
                session["name"] = shop["owner_name"]
                flash("Login successful.")
                return redirect("/owner_shop")
            flash("Login failed. Please check your email and password.")
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
        price = safe_int(request.form.get("price"), 0)
        quantity = safe_int(request.form.get("quantity"), 0)
        image_link = request.form.get("link", "").strip()
        if not all([name, description, image_link]):
            flash("Please provide product name, description, and image link.")
            return redirect("/owner_shop")
        if price <= 0:
            flash("Price must be greater than $0.")
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
                "price": price, 
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

@app.route("/delete/<id>")
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
    return render_template("customer_shop.html", products = list(db.Products.find({"email": email}).sort("name", 1)), cart_count = get_cart_count(), email = email, shop = shop)

def add_to_cart(product_id, redirect_target):
    quantity = safe_int(request.form.get("quantity"), 0)
    if quantity <= 0:
        flash("Please enter a valid quantity.")
        return redirect(redirect_target)
    try:
        product = db.Products.find_one({"_id": ObjectId(product_id)})
        if not product:
            flash("This item is no longer available.")
            return redirect(redirect_target)
        if quantity > product["quantity"]:
            flash(f"Only {product['quantity']} {product['name']}(s) are available in stock.")
            return redirect(redirect_target)
        db.Products.update_one({"_id": ObjectId(product_id)}, {"$inc": {"quantity": -quantity}})
        cart = get_cart()
        found = False
        for item in cart:
            if item["name"] == product["name"]:
                item["quantity"] += quantity
                found = True
                break
        if not found:
            cart.append({"name": product["name"], "quantity": quantity, "price": product["price"]})
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

@app.route("/remove_from_cart/<item_name>", methods = ["POST"])
def remove_from_cart(item_name):
    if "user_id" not in session:
        flash("Your session has expired.")
        return redirect("/")
    try:
        cart = get_cart()
        cart[:] = [item for item in cart if item["name"] != item_name]
        db.Carts.update_one({"_id": ObjectId(session["user_id"])}, {"$set": {"cart": cart}})
        flash(f"Removed {item_name} from cart.")
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
        item_name = request.form.get("item_name", "").strip()
        new_quantity = safe_int(request.form.get("quantity"), 0)
        if not item_name or new_quantity <= 0:
            flash("Invalid quantity.")
            return redirect("/view_cart")
        cart = get_cart()
        for item in cart:
            if item["name"] == item_name:
                old_quantity = item["quantity"]
                difference = old_quantity - new_quantity
                product = db.Products.find_one({"name": item_name})
                if product:
                    db.Products.update_one({"_id": product["_id"]}, {"$inc": {"quantity": difference}})
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
    cart = get_cart()
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
            flash("Thank you for shopping with One Stop Shop! Your order has been placed.")
    except Exception as e:
        print(f"Checkout error: {e}")
        flash("An error occurred during checkout. Please try again.")
    return redirect("/")

if __name__ == "__main__":
    app.run(debug = True)