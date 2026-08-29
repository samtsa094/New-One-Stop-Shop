import os
from flask import Flask, render_template, request, redirect, flash, session
from flask_pymongo import PyMongo
from bson.objectid import ObjectId
from passlib.hash import sha256_crypt
app = Flask(__name__)
app.config["MONGO_URI"] = os.getenv("MONGOURI", "mongodb://localhost:27017/one_stop_shop")
app.config["SECRET_KEY"] = os.getenv("SECRETKEY") or os.urandom(32)
mongo = PyMongo(app)
@app.route("/", methods = ["GET", "POST"])
def index():
    if "user_id" not in session:
        session["user_id"] = str(mongo.db.Carts.insert_one({"cart": []}).inserted_id)
    cart_count = len(mongo.db.Carts.find_one({"_id": ObjectId(session["user_id"])})["cart"])
    shops = list(mongo.db.Shops.find())
    products = list(mongo.db.Products.find())
    return render_template("index.html", shops = shops, products = products, cart_count = cart_count)
@app.route("/register", methods = ["GET", "POST"])
def register():
    flash("Successfully registered a shop")
    form_id = request.form.get("form_id")
    if form_id == "register_form":
        document = {}
        document["email"] = request.form.get("email")
        document["password"] = sha256_crypt.hash(request.form.get("password"))
        document["owner_name"] = request.form.get("owner_name")
        document["shop_name"] = request.form.get("shop_name")
        document["contact"] = request.form.get("contact")
        mongo.db.Shops.insert_one(document)
        return redirect("/")
@app.route("/owner_shop", methods = ["GET", "POST"])
def owner_shop():
    if "email" not in session:
        flash("You must first login")
        return redirect("/")
    products = list(mongo.db.Products.find({"email": session["email"]}))
    return render_template("owner_shop.html", products = products, name = session["name"])
@app.route("/login", methods = ["GET", "POST"])
def login():
    shops = mongo.db.Shops.find()
    for shop in shops:
        form_id = request.form.get("form_id")
        if form_id == "login_form":
            if request.form.get("email") == shop["email"]:
                password = shop["password"]
                email = shop["email"]
                if sha256_crypt.verify(request.form.get("password"), password):
                    session["email"] = email
                    session["name"] = shop["owner_name"]
                    flash("Login successful")
                    return redirect("/owner_shop")
                else:
                    flash("Password is incorrect")
                    return redirect("/")
    flash("Please register as a shop owner")
    return redirect("/")
@app.route("/logout", methods = ["GET", "POST"])
def logout():
    session.clear()
    flash("Logout successful")
    return redirect("/")
@app.route("/add_product", methods = ["GET", "POST"])
def add_product():
    flash("Product added successfully")
    form_id = request.form.get("form_id")
    if form_id == "add_product_form":
        document = {}
        document["name"] = request.form.get("name")
        document["description"] = request.form.get("description")
        document["price"] = int(request.form.get("price"))
        document["quantity"] = int(request.form.get("quantity"))
        document["link"] = request.form.get("link")
        document["email"] = session["email"]
        mongo.db.Products.insert_one(document)
        return redirect("/owner_shop")
@app.route("/add_stock/<id>", methods = ["GET", "POST"])
def add_stock(id):
    product = mongo.db.Products.find_one({"_id": ObjectId(id)})
    flash(f"{request.form.get('quantity')} {product['name']}(s) added to stock")
    mongo.db.Products.update_one({"_id": ObjectId(id)}, {"$inc": {"quantity": int(request.form.get("quantity"))}})
    return redirect("/owner_shop")
@app.route("/delete/<id>")
def delete(id):
    flash("Successfully deleted the product")
    mongo.db.Products.delete_one({"_id": ObjectId(id)})
    return redirect("/owner_shop")
@app.route("/view_shop/<email>", methods = ["GET", "POST"])
def view_shop(email):
    flash("Successfully entered the shop")
    if request.method == "GET":
        products = list(mongo.db.Products.find({"email": email}))
        cart_count = len(mongo.db.Carts.find_one({"_id": ObjectId(session["user_id"])})["cart"])
        return render_template("customer_shop.html", products = products, cart_count = cart_count, email = email)
@app.route("/add_cart_home/<id>", methods = ["GET", "POST"])
def add_cart_home(id):
    mongo.db.Products.update_one({"_id": ObjectId(id)}, {"$inc": {"quantity": -1 * int(request.form.get("quantity"))}})
    product = mongo.db.Products.find_one({"_id": ObjectId(id)})
    flash(f"Successfully added {request.form.get('quantity')} {product['name']}(s) to your cart")
    product_to_add = {}
    product_to_add["name"] = product["name"]
    product_to_add["quantity"] = int(request.form.get("quantity"))
    product_to_add["price"] = product["price"]
    mongo.db.Carts.update_one({"_id": ObjectId(session["user_id"])}, {"$addToSet": {"cart": product_to_add}})
    return redirect("/")
@app.route("/add_cart_shop/<id>/<email>", methods = ["GET", "POST"])
def add_cart_shop(id, email):
    mongo.db.Products.update_one({"_id": ObjectId(id)}, {"$inc": {"quantity": -1 * int(request.form.get("quantity"))}})
    product = mongo.db.Products.find_one({"_id": ObjectId(id)})
    flash(f"Successfully added {request.form.get('quantity')} {product['name']}(s) to your cart")
    product_to_add = {}
    product_to_add["name"] = product["name"]
    product_to_add["quantity"] = int(request.form.get("quantity"))
    product_to_add["price"] = product["price"]
    mongo.db.Carts.update_one({"_id": ObjectId(session["user_id"])}, {"$addToSet": {"cart": product_to_add}})
    return redirect(f"/view_shop/{email}")
@app.route("/view_cart", methods = ["GET", "POST"])
def view_cart():
    cart = list(mongo.db.Carts.find_one({"_id": ObjectId(session["user_id"])})["cart"])
    total = 0
    for i in cart:
        total += (i["quantity"] * i["price"])
    return render_template("checkout.html", cart = cart, total = total)
@app.route("/checkout", methods = ["GET", "POST"])
def checkout():
    session.pop("user_id")
    return redirect("/")
if __name__ == "__main__":
    app.run(debug = True)