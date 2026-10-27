# WindSight — UK Wind Generation Forecast Intelligence

WindSight is a wind generation forecast analytics platform that compares published wind forecasts with actual UK wind generation data from the official Elexon BMRS API. It calculates forecasting accuracy metrics, tracks forecast publication timestamps, and provides interactive dashboards for analysing forecast errors.

## 1. Live Application

- **Vercel Application:** [Open WindSight](https://windsight-alpha.vercel.app/)
- **Backend API (Render):** `https://windsight-api.onrender.com`
- **Database:** Neon.tech (PostgreSQL)

The frontend is deployed on Vercel, the backend API runs on Render, and Neon.tech provides persistent PostgreSQL database storage.

## 2. Project Structure

```text
WindSight/
├── backend/
│   ├── app/
│   │   ├── api/                 # API routes and response schemas
│   │   ├── analysis/            # Forecast selection, matching and metrics
│   │   ├── db/                  # Database models, sessions and repositories
│   │   ├── elexon/              # Elexon API client and data normalisation
│   │   ├── scripts/             # Data import and database status commands
│   │   ├── main.py              # FastAPI application entry point
│   │   ├── config.py            # Environment configuration
│   │   ├── models.py            # Domain models
│   │   ├── service.py           # Analytics services
│   │   ├── store.py             # Database access and storage
│   │   ├── importer.py          # Historical data import
│   │   ├── source.py            # Data source abstraction
│   │   └── export.py            # CSV export functionality
│   ├── alembic/                 # Database migration files
│   ├── data/
│   │   ├── snapshots/            # Historical Elexon data snapshots
│   │   └── cache/                # Cached upstream responses
│   ├── tests/                   # Backend automated tests
│   ├── Dockerfile               # Backend container configuration
│   ├── requirements.txt          # Python dependencies
│   ├── alembic.ini              # Database migration configuration
│   └── Procfile                  # Process configuration
│
├── frontend/
│   ├── src/
│   │   ├── components/           # Reusable UI components
│   │   ├── context/              # Shared cutoff configuration
│   │   ├── hooks/                # API and state management hooks
│   │   ├── lib/                  # API client and formatting utilities
│   │   ├── pages/                # Dashboard and analysis pages
│   │   ├── test/                 # Frontend automated tests
│   │   ├── App.tsx               # Application routing and layout
│   │   ├── main.tsx              # React entry point
│   │   ├── types.ts              # TypeScript API types
│   │   └── index.css             # Global styles
│   ├── index.html                # HTML entry point
│   ├── package.json              # Frontend dependencies and scripts
│   ├── package-lock.json         # Locked dependency versions
│   ├── vite.config.ts            # Vite and development configuration
│   ├── tsconfig.json             # TypeScript configuration
│   ├── vercel.json               # Vercel deployment configuration
│   ├── Dockerfile                # Frontend container configuration
│   └── nginx.conf                # Nginx configuration
│
├── .env.example                  # Example environment variables
├── .gitignore                    # Files excluded from Git
├── docker-compose.yml            # Local multi-container setup
├── render.yaml                   # Render deployment configuration
└── README.md                     # Project documentation
```

### Important Directories and Files

- **`backend/app/analysis/`** — Implements forecast selection based on decision cutoffs, matches forecasts with actual generation, and calculates accuracy metrics.
- **`backend/app/api/`** — Defines the backend API endpoints and response schemas.
- **`backend/app/db/`** — Handles database models, connections, repositories, and migrations.
- **`backend/app/elexon/`** — Fetches and normalises data from the Elexon BMRS API.
- **`backend/app/scripts/`** — Contains commands for importing historical data and checking database status.
- **`backend/data/snapshots/`** — Contains committed historical Elexon data used to initialise an empty database.
- **`backend/tests/`** — Contains backend tests for data processing, analytics, API behaviour, and persistence.
- **`frontend/src/pages/`** — Contains the Overview, Forecast Explorer, Accuracy Analysis, Methodology, and About pages.
- **`frontend/src/components/`** — Contains reusable interface components.
- **`frontend/src/lib/`** — Contains API communication and formatting utilities.
- **`frontend/vercel.json`** — Configures the frontend for Vercel deployment.
- **`render.yaml`** — Defines the Render deployment configuration.
- **`.env.example`** — Documents the environment variables required to configure the application.

## 3. How to Run the Application

### Prerequisites

Install the following software before running the project locally:

- Python 3.11 or later
- Node.js 20 or later
- npm
- Git

Docker is optional if you prefer to run both services using Docker Compose.

### Step 1: Clone the Repository

```bash
git clone <YOUR-GITHUB-REPOSITORY-URL>
cd WindSight
```

### Step 2: Start the Backend

Open a terminal and execute:

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment.

**Windows (Git Bash):**

```bash
source .venv/Scripts/activate
```

**Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1
```

**macOS/Linux:**

```bash
source .venv/bin/activate
```

Install the dependencies:

```bash
pip install -r requirements.txt
```

Create the database schema and import the historical data from the committed snapshots:

```bash
python -m app.scripts.import_historical_data --status --upgrade-schema

python -m app.scripts.import_historical_data --from 2026-01-01 --to 2026-01-31 --source snapshot
```

Start the FastAPI server:

```bash
uvicorn app.main:app --reload --port 8000
```

The backend API will be available at:

- API: `http://localhost:8000`
- API documentation: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/api/health`

### Step 3: Start the Frontend

Open a second terminal from the project root:

```bash
cd frontend
npm install
npm run dev
```

The frontend will be available at:

`http://localhost:5173`

The Vite development server proxies API requests to the backend running on port 8000.

### Step 4: Configure Environment Variables

For local configuration, refer to `.env.example`.

For production, configure the following variables in the respective hosting dashboards:

- **Render:** `DATABASE_URL`, `ENVIRONMENT`, `CORS_ORIGINS`, and other backend settings.
- **Vercel:** `VITE_API_BASE_URL`, pointing to the deployed Render backend.
- **Neon.tech:** Use the PostgreSQL connection string provided by Neon as the backend's `DATABASE_URL`.

Never commit database credentials, API tokens, or other secrets to the repository.

### Alternative: Run with Docker

If Docker is installed, you can start the application using:

```bash
docker compose up -d --build
```

Access the application at `http://localhost:3000`.

The backend API documentation is available at `http://localhost:8000/docs`.

To stop the services:

```bash
docker compose down
```

## 4. Deployment

WindSight uses the following deployment architecture:

- **Frontend — Vercel:** Hosts the React, TypeScript, and Vite application.
- **Backend — Render:** Hosts the Python FastAPI service and exposes the analytics API.
- **Database — Neon.tech:** Provides persistent PostgreSQL storage for actual generation records, forecast publications, and import history.

The frontend communicates with the backend through `VITE_API_BASE_URL`. The backend connects to PostgreSQL through `DATABASE_URL`.

Ensure that `CORS_ORIGINS` on Render includes the deployed Vercel application URL.

## 5. Technologies Used

- **Frontend:** React, TypeScript, Vite, Tailwind CSS, Recharts
- **Backend:** Python, FastAPI, SQLAlchemy, Alembic
- **Database:** PostgreSQL (Neon.tech), SQLite for local development
- **Data Source:** Elexon BMRS API
- **Deployment:** Vercel, Render, Neon.tech
- **Testing:** Pytest, Vitest

