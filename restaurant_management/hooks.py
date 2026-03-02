app_name = "restaurant_management"
app_title = "Restaurant Management"
app_publisher = "Restaurant Management"
app_description = "Restaurant Billing & Order Management for ERPNext - Dine-in & Parcel orders, KOT & Bill printing, Table management, Revenue analytics"
app_email = "info@restaurant.com"
app_license = "MIT"
app_version = "1.0.0"

# Required Apps
required_apps = ["frappe", "erpnext"]

# Includes in <head>
# ------------------

app_include_css = "/assets/restaurant_management/css/restaurant.css"
app_include_js = "/assets/restaurant_management/js/restaurant.js"

# Include js in page
# page_js = {"page" : "public/js/file.js"}

# Include css in page
# page_css = {"page" : "public/css/file.css"}

# Website — Public guest ordering pages
# -------
website_route_rules = [
	{"from_route": "/restaurant/order", "to_route": "restaurant/order"},
	{"from_route": "/restaurant/status", "to_route": "restaurant/status"},
	{"from_route": "/restaurant/qrcodes", "to_route": "restaurant/qrcodes"},
]

# Guest-facing methods (no login required)
guest_methods = {
	"restaurant_management.restaurant_management.guest_api.get_guest_menu": True,
	"restaurant_management.restaurant_management.guest_api.place_guest_order": True,
	"restaurant_management.restaurant_management.guest_api.get_order_status": True,
	"restaurant_management.restaurant_management.guest_api.get_table_qr_data": True,
}

# Installation
# ------------

# before_install = "restaurant_management.install.before_install"
after_install = "restaurant_management.install.after_install"

# Fixtures
# --------
fixtures = []

# Permissions
# -----------

has_permission = {}

# DocType Class
# ---------------

# Override standard doctype classes
override_doctype_class = {}

# Document Events
# ----------------

doc_events = {}

# Scheduled Tasks
# ----------------

scheduler_events = {}

# Jinja
# ----------

jinja = {}

# Override Methods
# ----------------

override_whitelisted_methods = {}

# Setup Wizard
# ------------

# before_wizard_complete = "restaurant_management.install.before_wizard_complete"
# after_wizard_complete = "restaurant_management.install.after_wizard_complete"
