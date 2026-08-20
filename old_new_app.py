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

def safe_int(value, default=0):
    try:
        n = int(value)
        return n if n > 0 else default
    except (TypeError, ValueError):
        return default


@app.route("/", methods=["GET", "POST"])
def index():
    session.setdefault("user_id", str(db.Carts.insert_one({"cart": []}).inserted_id))
    return render_template("index.html", shops=list(db.Shops.find().sort("shop_name", 1)), products=list(db.Products.find().sort("name", 1)), cart_count=get_cart_count())

@app.route("/register", methods=["GET", "POST"])
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
        db.Shops.insert_one({"email": email, "password": sha256_crypt.hash(password), "owner_name": owner_name, "shop_name": shop_name, "contact": contact})
        flash("Shop registered successfully.")
        return redirect("/")
    return redirect("/")

@app.route("/owner_shop", methods=["GET", "POST"])
def owner_shop():
    if "email" not in session:
        flash("You must first login.")
        return redirect("/")
    return render_template("owner_shop.html", products=list(db.Products.find({"email": session["email"]}).sort("name", 1)), name=session["name"])

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST" and request.form.get("form_id") == "login_form":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        shop = db.Shops.find_one({"email": email})
        if shop and sha256_crypt.verify(password, shop["password"]):
            session["email"] = shop["email"]
            session["name"] = shop["owner_name"]
            flash("Login successful.")
            return redirect("/owner_shop")
        flash("Login failed. Please check your email and password.")
        return redirect("/")
    return redirect("/")

@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    flash("Logout successful.")
    return redirect("/")

@app.route("/add_product", methods=["POST"])
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
        if not all([name, description, image_link]) or price <= 0 or quantity <= 0:
            flash("Please add a valid product name, description, price, quantity, and image link.")
            return redirect("/owner_shop")
        db.Products.insert_one({"name": name, "description": description, "price": price, "quantity": quantity, "link": image_link, "email": session["email"]})
        flash("Product added successfully.")
        return redirect("/owner_shop")
    return redirect("/owner_shop")

@app.route("/add_stock/<id>", methods=["POST"])
def add_stock(id):
    if "email" not in session:
        flash("You must be logged in as a shop owner.")
        return redirect("/")
    product = db.Products.find_one({"_id": ObjectId(id)})
    if not product:
        flash("Product not found.")
        return redirect("/owner_shop")
    quantity = safe_int(request.form.get("quantity"), 0)
    if quantity <= 0:
        flash("Please enter a valid quantity to add.")
        return redirect("/owner_shop")
    db.Products.update_one({"_id": ObjectId(id)}, {"$inc": {"quantity": quantity}})
    flash(f"{quantity} {product['name']}(s) added to stock.")
    return redirect("/owner_shop")

@app.route("/delete/<id>")
def delete(id):
    if "email" not in session:
        flash("Please login to manage your products.")
        return redirect("/")
    db.Products.delete_one({"_id": ObjectId(id)})
    flash("Product deleted successfully.")
    return redirect("/owner_shop")

@app.route("/view_shop/<email>", methods=["GET"])
@app.route("/shop/<email>", methods=["GET"])
def view_shop(email):
    shop = db.Shops.find_one({"email": email})
    if not shop:
        flash("That shop could not be found.")
        return redirect("/")
    return render_template("customer_shop.html", products=list(db.Products.find({"email": email}).sort("name", 1)), cart_count=get_cart_count(), email=email, shop=shop)

def add_to_cart(product_id, redirect_target):
    quantity = safe_int(request.form.get("quantity"), 0)
    if quantity <= 0:
        flash("Please enter a valid quantity.")
        return redirect(redirect_target)
    product = db.Products.find_one({"_id": ObjectId(product_id)})
    if not product:
        flash("This item is no longer available.")
        return redirect(redirect_target)
    if quantity > product["quantity"]:
        flash(f"Only {product['quantity']} {product['name']}(s) are available.")
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
    return redirect(redirect_target)

@app.route("/add_cart_home/<id>", methods=["POST"])
def add_cart_home(id):
    return add_to_cart(id, "/")

@app.route("/add_cart_shop/<id>/<email>", methods=["POST"])
def add_cart_shop(id, email):
    return add_to_cart(id, f"/shop/{email}")

@app.route("/view_cart", methods=["GET", "POST"])
def view_cart():
    cart = get_cart()
    total = sum(item["quantity"] * item["price"] for item in cart)
    return render_template("checkout.html", cart=cart, total=total)

@app.route("/checkout", methods=["POST"])
def checkout():
    if "user_id" in session:
        db.Carts.delete_one({"_id": ObjectId(session["user_id"])})
        session.pop("user_id", None)
    flash("Thank you for shopping with One Stop Shop!")
    return redirect("/")


if __name__ == "__main__":
    app.run(debug=True)
