# 🍽️ Restaurant Management for ERPNext

A complete **Restaurant Billing & Order Management** app built for **ERPNext v15 / Frappe v15**.  
Covers dine-in & parcel orders, table management, KOT & bill printing, revenue analytics, and ERPNext Sales Invoice integration.

> Inspired by [amutaher/Restaurant-Billing-System](https://github.com/amutaher/Restaurant-Billing-System) — rebuilt as a native Frappe/ERPNext app.

## 🚀 Features

### 🛒 Order Management
- Create and manage **Dine-in** and **Parcel** orders
- Interactive **POS page** for fast order-taking
- Menu items grouped by category with search/filter
- Quantity controls and real-time total calculation
- Special instructions / notes per order

### 🪑 Table Management
- Visual table grid with **color-coded status** (Available / Occupied / Reserved)
- Automatic table occupation when dine-in order is placed
- One-click **Clear Table** to complete order and free table
- Seating capacity tracking

### 🖨️ Printing
- **KOT (Kitchen Order Ticket)** — compact format for kitchen display
- **Bill/Receipt** — professional receipt with restaurant branding
- Both printable directly from the browser

### 📊 Revenue Analytics
- **Script Report** with date range filters and order type filters
- Bar charts showing revenue and order trends
- Summary cards: Total Revenue, Orders, Dine-in/Parcel split, Avg Order Value
- Built-in Excel/CSV export

### 💳 ERPNext Integration
- **Auto-create Sales Invoice** when order is completed (enabled by default)
- Links restaurant orders to ERPNext accounting
- Toggle on/off via Restaurant Settings

### 📤 Export & Sharing
- **Excel export** of revenue reports
- **WhatsApp** daily revenue summary sharing

## 📦 Installation

```bash
# Navigate to your bench directory
cd ~/frappe-bench

# Get the app
bench get-app https://github.com/YOUR_USERNAME/restaurant_management.git

# Install on your site
bench --site your-site.local install-app restaurant_management

# Run migrations
bench --site your-site.local migrate

# Clear cache
bench --site your-site.local clear-cache
bench build
```

## 🏗️ Setup

1. **Restaurant Settings** — Configure restaurant name, address, currency symbol, and feature toggles
2. **Menu Items** — Add your dishes with categories, prices, and images
3. **Tables** — 10 tables are created by default; add more as needed
4. **Start Taking Orders** — Open the **Restaurant POS** page from the workspace

## 📋 DocTypes

| DocType | Description |
|---------|-------------|
| **Restaurant Settings** | Singleton — restaurant config and feature toggles |
| **Restaurant Table** | Table with number, status, capacity |
| **Restaurant Menu Item** | Dish with name, group, price, availability |
| **Restaurant Order** | Order with type, table, items, totals, status |
| **Restaurant Order Item** | Child table — line items in an order |

## 🖥️ Pages & Reports

| Name | Type | Description |
|------|------|-------------|
| **Restaurant POS** | Page | Interactive order-taking interface |
| **Restaurant Revenue** | Script Report | Revenue analytics with charts |

## 📜 License

MIT License — see [license.txt](license.txt)
