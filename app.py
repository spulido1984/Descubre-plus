"""Descubre+ MVP API. Run with uvicorn app:app --reload."""
import hashlib
import hmac
import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent
DB = Path(os.environ.get('DESCUBRE_DB', str(BASE / 'descubre.db')))
app = FastAPI(title='Descubre+ API', version='0.3.0')

@contextmanager
def db():
    conn = sqlite3.connect(DB, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def init():
    DB.parent.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('customer','merchant','admin')), token_hash TEXT UNIQUE);
        CREATE TABLE IF NOT EXISTS restaurants(id INTEGER PRIMARY KEY, owner_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, category TEXT NOT NULL, postal_code TEXT NOT NULL, description TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS promotions(id INTEGER PRIMARY KEY, restaurant_id INTEGER NOT NULL REFERENCES restaurants(id), title TEXT NOT NULL, product TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY, code_hash TEXT UNIQUE NOT NULL, customer_id INTEGER NOT NULL REFERENCES users(id), promotion_id INTEGER NOT NULL REFERENCES promotions(id), status TEXT NOT NULL DEFAULT 'issued' CHECK(status IN ('issued','redeemed')), issued_at TEXT NOT NULL, redeemed_at TEXT);
        ''')

@app.on_event('startup')
def startup():
    init()

class Register(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=10, max_length=128)
    role: str = 'customer'

class Login(BaseModel):
    email: str
    password: str

class RestaurantIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=2, max_length=80)
    postal_code: str = Field(pattern=r'^\d{5}$')
    description: str = Field(default='', max_length=1000)

class PromotionIn(BaseModel):
    restaurant_id: int
    title: str = Field(min_length=3, max_length=150)
    product: str = Field(min_length=2, max_length=150)

class RedeemIn(BaseModel):
    code: str = Field(min_length=16, max_length=256)

def hash_password(password, salt):
    return hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 310000).hex()

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def auth(authorization, roles=None):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Inicia sesion')
    with db() as c:
        u = c.execute('SELECT id,email,role FROM users WHERE token_hash=?', (digest(authorization[7:]),)).fetchone()
    if not u:
        raise HTTPException(401, 'Sesion invalida')
    if roles and u['role'] not in roles:
        raise HTTPException(403, 'Acceso no autorizado')
    return dict(u)

@app.get('/')
def home():
    return FileResponse(BASE / 'static' / 'app.html')

@app.post('/api/register', status_code=201)
def register(body: Register):
    if body.role not in ('customer', 'merchant'):
        raise HTTPException(400, 'Rol no permitido')
    email = body.email.strip().lower()
    if '@' not in email or email.startswith('@'):
        raise HTTPException(422, 'Correo invalido')
    salt = secrets.token_hex(16)
    try:
        with db() as c:
            c.execute('INSERT INTO users(email,salt,password_hash,role) VALUES(?,?,?,?)', (email, salt, hash_password(body.password, salt), body.role))
    except sqlite3.IntegrityError:
        raise HTTPException(409, 'Correo registrado')
    return {'message': 'Cuenta creada'}

@app.post('/api/login')
def login(body: Login):
    with db() as c:
        u = c.execute('SELECT * FROM users WHERE email=?', (body.email.strip().lower(),)).fetchone()
        if not u or not hmac.compare_digest(u['password_hash'], hash_password(body.password, u['salt'])):
            raise HTTPException(401, 'Credenciales incorrectas')
        token = secrets.token_urlsafe(32)
        c.execute('UPDATE users SET token_hash=? WHERE id=?', (digest(token), u['id']))
        return {'token': token, 'role': u['role']}

@app.get('/api/restaurants')
def restaurants(postal_code: str | None = None):
    with db() as c:
        sql = '''SELECT r.*, p.id AS promotion_id, p.title AS promotion, p.product FROM restaurants r LEFT JOIN promotions p ON p.restaurant_id=r.id AND p.active=1'''
        args = ()
        if postal_code:
            sql += ' WHERE r.postal_code=?'
            args = (postal_code,)
        return [dict(x) for x in c.execute(sql + ' ORDER BY r.id DESC', args)]

@app.post('/api/restaurants', status_code=201)
def create_restaurant(body: RestaurantIn, authorization: str | None = Header(default=None)):
    user = auth(authorization, ('merchant',))
    with db() as c:
        cur = c.execute('INSERT INTO restaurants(owner_id,name,category,postal_code,description) VALUES(?,?,?,?,?)', (user['id'], body.name, body.category, body.postal_code, body.description))
        return {'id': cur.lastrowid}

@app.post('/api/promotions', status_code=201)
def create_promotion(body: PromotionIn, authorization: str | None = Header(default=None)):
    user = auth(authorization, ('merchant',))
    with db() as c:
        owner = c.execute('SELECT owner_id FROM restaurants WHERE id=?', (body.restaurant_id,)).fetchone()
        if not owner or owner['owner_id'] != user['id']:
            raise HTTPException(403, 'Restaurante no autorizado')
        cur = c.execute('INSERT INTO promotions(restaurant_id,title,product) VALUES(?,?,?)', (body.restaurant_id, body.title, body.product))
        return {'id': cur.lastrowid}

@app.post('/api/promotions/{promotion_id}/claim', status_code=201)
def claim(promotion_id: int, authorization: str | None = Header(default=None)):
    user = auth(authorization, ('customer',))
    code = secrets.token_urlsafe(24)
    with db() as c:
        promo = c.execute('SELECT id FROM promotions WHERE id=? AND active=1', (promotion_id,)).fetchone()
        if not promo:
            raise HTTPException(404, 'Promocion no disponible')
        c.execute('INSERT INTO tickets(code_hash,customer_id,promotion_id,issued_at) VALUES(?,?,?,?)', (digest(code), user['id'], promotion_id, datetime.now(timezone.utc).isoformat()))
    return {'code': code, 'status': 'issued'}

@app.post('/api/tickets/redeem')
def redeem(body: RedeemIn, authorization: str | None = Header(default=None)):
    user = auth(authorization, ('merchant',))
    with db() as c:
        t = c.execute('''SELECT t.id,t.status,p.product,p.title,r.owner_id FROM tickets t JOIN promotions p ON p.id=t.promotion_id JOIN restaurants r ON r.id=p.restaurant_id WHERE t.code_hash=?''', (digest(body.code),)).fetchone()
        if not t:
            raise HTTPException(404, 'Codigo no encontrado')
        if t['owner_id'] != user['id']:
            raise HTTPException(403, 'Este codigo corresponde a otro negocio')
        if t['status'] != 'issued':
            raise HTTPException(409, 'Codigo ya canjeado')
        updated = c.execute("UPDATE tickets SET status='redeemed',redeemed_at=? WHERE id=? AND status='issued'", (datetime.now(timezone.utc).isoformat(), t['id']))
        if updated.rowcount != 1:
            raise HTTPException(409, 'Codigo ya canjeado')
        return {'status': 'redeemed', 'promotion': t['title'], 'deliver': t['product']}

@app.get('/api/me/visits')
def visits(authorization: str | None = Header(default=None)):
    user = auth(authorization)
    with db() as c:
        if user['role'] == 'merchant':
            rows = c.execute('''SELECT t.id,t.status,t.issued_at,t.redeemed_at,r.name,p.title FROM tickets t JOIN promotions p ON p.id=t.promotion_id JOIN restaurants r ON r.id=p.restaurant_id WHERE r.owner_id=? ORDER BY t.id DESC''', (user['id'],))
        else:
            rows = c.execute('''SELECT t.id,t.status,t.issued_at,t.redeemed_at,r.name,p.title FROM tickets t JOIN promotions p ON p.id=t.promotion_id JOIN restaurants r ON r.id=p.restaurant_id WHERE t.customer_id=? ORDER BY t.id DESC''', (user['id'],))
        return [dict(x) for x in rows]

@app.get('/api/me/restaurants')
def my_restaurants(authorization: str | None = Header(default=None)):
    user = auth(authorization, ('merchant',))
    with db() as c:
        return [dict(x) for x in c.execute('SELECT id,name,category,postal_code,description FROM restaurants WHERE owner_id=? ORDER BY id DESC', (user['id'],))]
