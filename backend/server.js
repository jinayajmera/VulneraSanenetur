require('dotenv').config({ path: '../.env' });
const express = require('express');
const helmet = require('helmet');
const morgan = require('morgan');
const cors = require('cors');
const jwt = require('jsonwebtoken');
const bcrypt = require('bcrypt');
const Database = require('better-sqlite3');
const { createProxyMiddleware } = require('http-proxy-middleware');

const app = express();
const PORT = 8080;
const PYTHON_BACKEND = 'http://127.0.0.1:8000';
const JWT_SECRET = 'super-secret-robosurge-key-change-in-prod';

// ==========================================
// 1. HTTP SECURITY & LOGGING
// ==========================================
app.use(helmet({
    contentSecurityPolicy: {
        directives: {
            defaultSrc: ["'self'"],
            imgSrc: ["'self'", "data:", PYTHON_BACKEND],
            connectSrc: ["'self'", "ws:", "wss:", "http://localhost:8080"],
            styleSrc: ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
            fontSrc: ["'self'", "https://fonts.gstatic.com"]
        }
    }
}));
app.use(morgan('dev'));
app.use(cors());

// Parse JSON bodies (skip for proxy routes)
app.use((req, res, next) => {
    if (req.path.startsWith('/api/camera') || req.path === '/api/execute' || req.path === '/api/abort') {
        next();
    } else {
        express.json()(req, res, next);
    }
});

// ==========================================
// 2. SQLITE DATABASE SETUP
// ==========================================
const db = new Database('./robosurge.db');
db.pragma('journal_mode = WAL');

// Create Users Table
db.prepare(`
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL
    )
`).run();

// Create Jobs Table (SQLite Background Worker Queue)
db.prepare(`
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,
        payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        result TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
`).run();

// Default Admin User
const adminExists = db.prepare(`SELECT count(*) as count FROM users`).get();
if (adminExists.count === 0) {
    const hash = bcrypt.hashSync('admin123', 10);
    db.prepare(`INSERT INTO users (username, password, role) VALUES (?, ?, ?)`).run('admin', hash, 'admin');
    console.log("Created default admin user (admin / admin123)");
}

// ==========================================
// 3. AUTHENTICATION (RBAC & JWT)
// ==========================================
const authMiddleware = (allowedRoles = []) => {
    return (req, res, next) => {
        const authHeader = req.headers.authorization;
        if (!authHeader || !authHeader.startsWith('Bearer ')) {
            return res.status(401).json({ error: 'Missing or invalid token' });
        }
        
        const token = authHeader.split(' ')[1];
        try {
            const decoded = jwt.verify(token, JWT_SECRET);
            if (allowedRoles.length > 0 && !allowedRoles.includes(decoded.role)) {
                return res.status(403).json({ error: 'Forbidden: insufficient role permissions' });
            }
            req.user = decoded;
            next();
        } catch (err) {
            return res.status(401).json({ error: 'Invalid token' });
        }
    };
};

app.post('/auth/signup', authMiddleware(['admin']), (req, res) => {
    const { username, password, role } = req.body;
    if (!username || !password) return res.status(400).json({ error: "Missing fields" });

    const userRole = (role === 'admin' || role === 'doctor') ? role : 'doctor';
    try {
        const hash = bcrypt.hashSync(password, 10);
        db.prepare(`INSERT INTO users (username, password, role) VALUES (?, ?, ?)`).run(username, hash, userRole);
        res.json({ message: "User created successfully" });
    } catch (e) {
        res.status(500).json({ error: "Could not create user (maybe username exists)" });
    }
});

app.post('/auth/login', (req, res) => {
    const { username, password } = req.body;
    const user = db.prepare(`SELECT * FROM users WHERE username = ?`).get(username);
    
    if (!user || !bcrypt.compareSync(password, user.password)) {
        return res.status(401).json({ error: "Invalid credentials" });
    }

    const token = jwt.sign({ id: user.id, username: user.username, role: user.role }, JWT_SECRET, { expiresIn: '24h' });
    res.json({ token, role: user.role });
});

// ==========================================
// 4. API GATEWAY & PROXY TO PYTHON
// ==========================================
const secureApi = express.Router();
secureApi.use(authMiddleware(['admin', 'doctor']));

// Transparent Proxies
secureApi.use('/camera/feed', createProxyMiddleware({ target: PYTHON_BACKEND, changeOrigin: true }));
secureApi.use('/execute', createProxyMiddleware({ target: PYTHON_BACKEND, changeOrigin: true }));
secureApi.use('/abort', createProxyMiddleware({ target: PYTHON_BACKEND, changeOrigin: true }));

// NL Translation Interceptor for /status
let globalLastPlanStr = "";

secureApi.get('/status', async (req, res) => {
    try {
        const r = await fetch(PYTHON_BACKEND + '/api/status');
        const data = await r.json();

        if (data.planning && data.planning.plan) {
            const currentPlanStr = JSON.stringify(data.planning.plan);
            
            if (currentPlanStr !== globalLastPlanStr) {
                globalLastPlanStr = currentPlanStr;
                // Add a job to our SQLite queue
                db.prepare(`INSERT INTO jobs (type, payload, status) VALUES (?, ?, ?)`).run('translate_plan', currentPlanStr, 'pending');
                console.log("[Queue] Added translation job for new procedure plan.");
            }

            // Fetch the most recent completed translation job for this plan
            const latestJob = db.prepare(`SELECT result FROM jobs WHERE type = 'translate_plan' AND status = 'completed' AND payload = ? ORDER BY id DESC LIMIT 1`).get(currentPlanStr);
            if (latestJob && latestJob.result) {
                data.planning.nl_translation = latestJob.result;
            }
        } else {
            globalLastPlanStr = "";
        }

        res.json(data);
    } catch (e) {
        res.status(500).json({ error: "Python backend unreachable" });
    }
});

// Command Endpoint
secureApi.post('/command', async (req, res) => {
    try {
        const r = await fetch(PYTHON_BACKEND + '/api/command', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(req.body)
        });
        const data = await r.json();
        res.status(r.status).json(data);
    } catch(e) {
        res.status(500).json({ error: "Failed to send command" });
    }
});

app.use('/api', secureApi);

// ==========================================
// 5. STATIC FILES (REACT DASHBOARD)
// ==========================================
app.use('/', express.static('../frontend/dist'));


// ==========================================
// 6. SQLITE BACKGROUND QUEUE WORKER
// ==========================================
async function processQueue() {
    // Transaction to safely pick up a job
    const job = db.transaction(() => {
        const pendingJob = db.prepare(`SELECT * FROM jobs WHERE status = 'pending' LIMIT 1`).get();
        if (pendingJob) {
            db.prepare(`UPDATE jobs SET status = 'processing' WHERE id = ?`).run(pendingJob.id);
        }
        return pendingJob;
    })();

    if (!job) return; // Queue is empty

    console.log(`[Worker] Processing Job #${job.id}: ${job.type}`);
    
    try {
        if (job.type === 'translate_plan') {
            const groqKey = process.env.GROQ_API_KEY;
            if (!groqKey) throw new Error("GROQ_API_KEY missing");

            const prompt = "You are a surgical assistant. Explain the following surgical procedure plan JSON in plain natural language (1-2 paragraphs) for a human doctor to quickly verify before execution. Highlight the procedure type, rationale, and any safety notes. Do not output markdown code blocks. Here is the plan:\n" + job.payload;
            
            const reqBody = {
                model: process.env.GROQ_MODEL || "qwen/qwen3.8-27b",
                messages: [
                    { role: "system", content: "You are a helpful surgical robot interpreter." },
                    { role: "user", content: prompt }
                ],
                temperature: 0.0
            };

            const r = await fetch("https://api.groq.com/openai/v1/chat/completions", {
                method: "POST",
                headers: { "Content-Type": "application/json", "Authorization": `Bearer ${groqKey}` },
                body: JSON.stringify(reqBody)
            });

            if (!r.ok) throw new Error(`Groq API Error: ${r.statusText}`);
            
            const data = await r.json();
            const resultText = data.choices?.[0]?.message?.content || "Translation failed to parse.";
            
            db.prepare(`UPDATE jobs SET status = 'completed', result = ? WHERE id = ?`).run(resultText, job.id);
            console.log(`[Worker] Finished Job #${job.id}`);
        } else {
            throw new Error(`Unknown job type: ${job.type}`);
        }
    } catch (e) {
        console.error(`[Worker] Failed Job #${job.id}:`, e.message);
        db.prepare(`UPDATE jobs SET status = 'failed', result = ? WHERE id = ?`).run(e.message, job.id);
    }
}

// Polling interval for background worker
setInterval(processQueue, 2000);


// ==========================================
// START SERVER
// ==========================================
app.listen(PORT, () => {
    console.log(`Express Gateway & Worker Queue listening on port ${PORT}`);
});
