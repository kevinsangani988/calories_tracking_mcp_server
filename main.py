from fastmcp import FastMCP
import sqlite3
import os
from datetime import date
from pathlib import Path
from typing import Dict

DB_LOCATIONS = [
    Path("/data/nutrition.db"),    
    Path("/tmp/nutrition.db"),       
    Path("./nutrition.db"),          
]

DB_PATH = None
for location in DB_LOCATIONS:
    try:
        
        location.parent.mkdir(parents=True, exist_ok=True)
        
        test_file = location.parent / ".write_test"
        test_file.touch()
        test_file.unlink()

        DB_PATH = location
        print(f"Using writable database location: {DB_PATH}")
        break
    except (OSError, PermissionError) as e:
        print(f"✗ Cannot write to {location}: {e}")
        continue

if DB_PATH is None:
    raise RuntimeError("No writable location found for database!")

mcp = FastMCP("Nutrition & Health Tracker")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS foods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE,
                calories INTEGER,
                protein REAL,
                carbs REAL,
                fat REAL
            )
            """
        )

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                food_id INTEGER,
                quantity REAL,
                log_date TEXT,
                meal TEXT,
                FOREIGN KEY(food_id) REFERENCES foods(id)
            )
            """
        )

        cur = db.execute("PRAGMA table_info(logs)")
        cols = [r[1] if isinstance(r, tuple) else r["name"] for r in cur.fetchall()]
        if "meal" not in cols:
            try:
                db.execute("ALTER TABLE logs ADD COLUMN meal TEXT")
            except Exception:
                pass

        db.execute(
            """
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                daily_calories INTEGER
            )
            """
        )

        db.execute(
            "INSERT OR IGNORE INTO goals (id, daily_calories) VALUES (1, 2000)"
        )

        db.commit()
        print(f"✓ Database initialized successfully at {DB_PATH}")

init_db()

@mcp.tool()
def add_food(
    name: str,
    calories: int,
    protein: float,
    carbs: float,
    fat: float
) -> Dict:
    """Add or update a food."""
    with get_db() as db:
        db.execute(
            """
            INSERT OR REPLACE INTO foods
            (name, calories, protein, carbs, fat)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, calories, protein, carbs, fat),
        )
        db.commit()
        return {
            "status": "ok",
            "food": name,
            "db_path": str(DB_PATH),
        }

@mcp.tool()
def log_food(name: str, quantity: float, meal: str = "unspecified") -> Dict:
    """Log food eaten today (quantity = servings) and record meal name/type."""
    with get_db() as db:
        cur = db.execute(
            "SELECT id FROM foods WHERE name = ?",
            (name,),
        )
        row = cur.fetchone()
        if not row:
            return {"status": "error", "message": "Food not found"}

        db.execute(
            """
            INSERT INTO logs (food_id, quantity, log_date, meal)
            VALUES (?, ?, ?, ?)
            """,
            (row["id"], quantity, date.today().isoformat(), meal),
        )
        db.commit()

        return {
            "status": "ok",
            "food": name,
            "quantity": quantity,
            "meal": meal,
        }


@mcp.tool()
def get_meals(date_str: str = None) -> Dict:
    """Get meals and their logged foods for a given date (ISO). Defaults to today."""
    if not date_str:
        date_str = date.today().isoformat()

    with get_db() as db:
        cur = db.execute(
            """
            SELECT
                l.id,
                f.name AS food,
                l.quantity,
                l.meal,
                f.calories,
                f.protein,
                f.carbs,
                f.fat
            FROM logs l
            JOIN foods f ON l.food_id = f.id
            WHERE l.log_date = ?
            """,
            (date_str,),
        )

        meals = {}
        for r in cur.fetchall():
            meal_name = r["meal"] or "unspecified"
            meals.setdefault(meal_name, []).append(
                {
                    "log_id": r["id"],
                    "food": r["food"],
                    "quantity": r["quantity"],
                    "calories_per_serving": r["calories"],
                    "protein_per_serving": r["protein"],
                    "carbs_per_serving": r["carbs"],
                    "fat_per_serving": r["fat"],
                    "calories_total": r["calories"] * r["quantity"],
                }
            )

        return {"date": date_str, "meals": meals}

@mcp.tool()
def set_daily_calorie_goal(calories: int) -> Dict:
    """Set daily calorie goal."""
    with get_db() as db:
        db.execute(
            "UPDATE goals SET daily_calories = ? WHERE id = 1",
            (calories,),
        )
        db.commit()
        return {
            "status": "ok",
            "daily_calories": calories,
        }

@mcp.tool()
def today_summary() -> Dict:
    """Get today's calorie & macro summary."""
    with get_db() as db:
        cur = db.execute(
            """
            SELECT
                f.calories,
                f.protein,
                f.carbs,
                f.fat,
                l.quantity
            FROM logs l
            JOIN foods f ON l.food_id = f.id
            WHERE l.log_date = ?
            """,
            (date.today().isoformat(),),
        )

        totals = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}

        for row in cur.fetchall():
            totals["calories"] += row["calories"] * row["quantity"]
            totals["protein"] += row["protein"] * row["quantity"]
            totals["carbs"] += row["carbs"] * row["quantity"]
            totals["fat"] += row["fat"] * row["quantity"]

        goal = db.execute(
            "SELECT daily_calories FROM goals WHERE id = 1"
        ).fetchone()["daily_calories"]

        return {
            "totals": totals,
            "goal": goal,
            "remaining_calories": goal - totals["calories"],
        }

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)
