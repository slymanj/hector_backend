# Hector Investment API

A FastAPI-based **crypto investment platform**. Investors connect multi-chain wallets (Hedera, Bitcoin, Ethereum, Solana, USDT, and more), allocate capital into investment products, and track portfolios with transparent on-chain settlement where available.

> Full model and system documentation: **[ARCHITECTURE.md](./ARCHITECTURE.md)**

## Features

- **Investor accounts**: Roles `investor`, `fund_manager`, `admin` with email OTP verification
- **Investment products**: Fund managers create products with APY, risk, min ticket, lock period, accepted assets
- **Multi-chain wallets**: Connect BTC, ETH, SOL, BNB, Polygon, USDT, USDC; custodial HBAR created at signup
- **Investments**: Place capital into products (live HBAR transfers; external chains with tx hash confirmation)
- **Portfolio**: Positions list, projected payouts, portfolio summary
- **P2P HBAR**: Peer transfers between Hedera accounts
- **Transaction tracing**: Hedera Mirror Node + DB investment lookup
- **AI analytics**: Category mix, investor score, product recommendations
- **Profile & security**: JWT auth, wallet export, encrypted custodial keys
- **PostgreSQL + Alembic**, Docker, Celery/Redis, rate limiting

## Technology Stack

- **Backend**: FastAPI (Python 3.12)
- **Database**: PostgreSQL + SQLAlchemy + Alembic
- **Blockchain**: Hedera SDK (custodial HBAR); multi-chain address linking for BTC/ETH/etc.
- **Auth**: JWT, roles investor / admin / fund_manager
- **Analytics**: Pandas, NumPy, Scikit-learn
- **Tasks / cache**: Celery, Redis
- **Email**: Brevo/SendGrid
- **Security**: Fernet private-key encryption, bcrypt

## Quick Start

### Prerequisites

- Python 3.12+
- Docker and Docker Compose
- PostgreSQL (or use Docker container)

### Environment Setup

1. **Clone the repository**
   ```bash
   # Local project — no remote. From the workspace root:
   cd hector_backend
   ```

2. **Create virtual environment**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Environment Configuration**
   ```bash
   cp .env.sample .env
   ```

   Configure the following in your `.env` file:
   ```env
   # Database Configuration
   DB_HOST=localhost
   DB_PORT=5432
   DB_USER=your_db_user
   DB_PASSWORD=your_db_password
   DB_NAME=kanec_db

   # JWT Configuration
   SECRET_KEY=your-secret-key-here
   ALGORITHM=HS256
   ACCESS_TOKEN_EXPIRE_MINUTES=60

   # Hedera Configuration (custodial HBAR)
   HEDERA_NETWORK=testnet
   HEDERA_OPERATOR_ID=your-hedera-account-id
   HEDERA_OPERATOR_KEY=your-hedera-private-key
   PRIVATE_KEY_ENCRYPTION_KEY=your-32-character-encryption-key

   # Multi-chain (see NETWORK_SETUP.md + .env.sample)
   ENABLED_CHAINS=hedera,ethereum,bitcoin,solana,bnb,polygon,usdt,usdc
   ETHEREUM_RPC_URL=https://eth-sepolia.g.alchemy.com/v2/YOUR_KEY
   ETHEREUM_NETWORK=sepolia
   BITCOIN_API_URL=https://blockstream.info/testnet/api
   BITCOIN_NETWORK=testnet
   SOLANA_RPC_URL=https://api.devnet.solana.com
   SOLANA_NETWORK=devnet
   BNB_RPC_URL=https://data-seed-prebsc-1-s1.binance.org:8545
   POLYGON_RPC_URL=https://rpc-amoy.polygon.technology

   # Email Configuration (choose one)
   BREVO_API_KEY=your-brevo-api-key
   # OR
   MAIL_FROM=your-email@example.com
   MAIL_FROM_NAME=Hector API

   # Redis Configuration
   REDIS_HOST=localhost
   REDIS_PORT=6379
   REDIS_DB=0
   REDIS_PASSWORD=your-redis-password

   # Celery Configuration
   CELERY_BROKER_URL=redis://localhost:6379/0
   CELERY_RESULT_BACKEND=redis://localhost:6379/0

   # CORS Origins
   BACKEND_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
   ```

### Database Setup

1. **Create PostgreSQL database**
   ```sql
   CREATE USER kanec_user WITH PASSWORD 'your_password';
   CREATE DATABASE kanec_db;
   GRANT ALL PRIVILEGES ON DATABASE kanec_db TO kanec_user;
   ```

2. **Run database migrations**
   ```bash
   alembic upgrade head
   ```

3. **Seed the database (optional)**
   ```bash
   python scripts/seed.py
   ```

### Running the Application

#### Development Mode
```bash
python main.py
```
The API will be available at `http://localhost:8000` with root path `/kanec`

#### Using Docker Compose (Development)
```bash
docker-compose up --build
```
The API will be available at `http://localhost:7006`

#### Using Docker Compose (Staging)
```bash
docker-compose -f docker-compose.staging.yml up --build
```

#### Using Docker Compose (Production)
```bash
docker-compose -f docker-compose.prod.yml up --build
```

#### Using Docker (Standalone)
```bash
docker build -t kanec-api .
docker run -p 7001:7001 --env-file .env kanec-api
```

## API Documentation

Once the server is running, visit:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **Health Check**: `http://localhost:8000/` (returns `{"status": "ok"}`)

## AI_Analytics Features

The platform provides comprehensive analytics capabilities powered by AI and machine learning:

### User Insights
- **Personalized Analytics**: Category mix, investment frequency, investor score
- **ML-Powered Recommendations**: Product suggestions from portfolio history
- **Investor Scoring**: Multi-factor levels (Beginner → Whale)
- **Comparative Analysis**: Percentile ranking among investors

### Platform Analytics
- **Global Statistics**: Total investments, capital raised, products, investors
- **Category Analytics**: Top categories by capital with growth metrics
- **Product Analytics**: Performance and completion tracking
- **Real-time Activity**: Recent investments and product creation

### Data-Driven Features
- **Trend Analysis**: Monthly investment patterns
- **Predictive Insights**: Frequency and category growth signals
- **Smart Recommendations**: Content-based product suggestions

## API Endpoints

### Authentication & User Management
- `POST /api/v1/auth/register` - Register new user with email verification
- `POST /api/v1/auth/login` - User login (OAuth2 password flow)
- `POST /api/v1/auth/login_swagger` - Login via Swagger UI
- `GET /api/v1/auth/me` - Get current user details
- `GET /api/v1/auth/profile` - Get user profile with wallet balance
- `PUT /api/v1/auth/profile` - Update user profile
- `PATCH /api/v1/auth/profile` - Partially update user profile
- `POST /api/v1/auth/change-password` - Change user password
- `DELETE /api/v1/auth/account` - Delete user account
- `POST /api/v1/auth/export-wallet` - Export custodial key (password + rate limit required)
- `POST /api/v1/auth/verify-email` - Verify email with OTP
- `POST /api/v1/auth/resend-verification` - Resend email verification OTP
- `GET /api/v1/auth/verification-status` - Check email verification status
- `POST /api/v1/auth/forgot-password` - Request password reset OTP
- `POST /api/v1/auth/reset-password` - Reset password with OTP

### Projects
### Investment products (`/projects`)
- `POST /api/v1/projects/` - Create investment product (admin / fund_manager)
- `POST /api/v1/projects/{project_id}/image` - Upload product image
- `GET /api/v1/projects/` - List verified products
- `GET /api/v1/projects/marketplace/open` - Open marketplace products
- `GET /api/v1/projects/{project_id}` - Product details
- `GET /api/v1/projects/{project_id}/transparency` - Treasury + investment ledger
- `PATCH /api/v1/projects/{project_id}/verify` - Verify product (admin)

### Investments
- `POST /api/v1/investments/` - Invest capital (HBAR on-chain or multi-asset record)
- `GET /api/v1/investments/my-investments` - Investor positions
- `GET /api/v1/investments/portfolio` - Portfolio summary
- `POST /api/v1/investments/{id}/confirm` - Confirm pending external investment with tx_hash

### Wallets (multi-chain)
- `GET /api/v1/wallets/supported-chains` - BTC, ETH, HBAR, SOL, USDT, …
- `POST /api/v1/wallets/connect` - Connect external wallet
- `GET /api/v1/wallets/` - List linked wallets
- `PATCH|DELETE /api/v1/wallets/{id}` - Update / disconnect
- `GET /api/v1/wallets/{id}/balance` - Balance (live for HBAR)

### P2P Transfers
- `POST /api/v1/p2p/transfer` - Transfer HBAR between user wallets with memo support
- `GET /api/v1/p2p/balance` - Get user HBAR balance
- `POST /api/v1/p2p/validate-wallet` - Validate Hedera wallet address

### Transaction Tracing
- `GET /api/v1/trace/trace/{tx_hash}` - Trace investment settlement on Hedera Mirror Node

### AI Analytics
- `GET /api/v1/analytics/user/insights` - Investor insights and product recommendations
- `GET /api/v1/analytics/global/stats` - Global capital / product stats
- `GET /api/v1/analytics/platform/overview` - Platform overview with categories
- `GET /api/v1/analytics/project/{project_id}` - Product analytics
- `GET /api/v1/analytics/categories/top` - Top categories by capital raised
- `GET /api/v1/analytics/user/compare` - Compare investor vs platform averages

## User Roles & Permissions

- **Investor**: Connect wallets, invest, P2P HBAR, portfolio, personal analytics
- **Fund manager**: Investor permissions + create/manage investment products
- **Admin**: All permissions + verify products

## P2P Transfers

The platform supports direct HBAR transfers between users:

### Features
- **Secure Transfers**: Encrypted private key handling with balance validation
- **Memo Support**: Add transaction memos for transfer tracking
- **Balance Checking**: Real-time balance verification before transfers
- **Wallet Validation**: Validate recipient wallet addresses
- **Transfer Limits**: Maximum 10,000 HBAR per transfer for security

### Transfer Process
1. User initiates transfer with recipient wallet, amount, and optional memo
2. System validates sender balance, recipient wallet format, and transfer limits (max 10,000 HBAR)
3. Transaction is submitted to Hedera network with memo support
4. Transfer status is tracked and confirmed via transaction hash

## Profile Management

### Features
- **Profile Updates**: Full profile information management
- **Password Security**: Secure password changes with validation
- **Wallet Balance**: Real-time HBAR balance display
- **Account Deletion**: Complete account removal with data cleanup
- **Email Verification**: OTP-based email verification system

### Security Features
- **Private Key Encryption**: AES encryption for stored private keys
- **JWT Authentication**: Secure token-based authentication
- **Rate Limiting**: API rate limiting to prevent abuse
- **Input Validation**: Comprehensive input sanitization

## Email & OTP Verification

### Features
- **Email Verification**: OTP-based email verification for new accounts
- **Password Reset**: Secure password reset with OTP codes
- **Multiple Providers**: Support for Brevo and SendGrid email services
- **OTP Management**: Secure OTP generation and validation
- **Resend Functionality**: Ability to resend verification codes

### Verification Process
1. User registers or requests password reset
2. OTP code sent to email address
3. User enters OTP for verification
4. Account activated or password reset completed

## Hedera Integration

- Automatic custodial HBAR wallets for investors and product treasuries
- On-chain investment transfers
- Mirror Node verification and tracing

See **ARCHITECTURE.md** for models and **NETWORK_SETUP.md** for multi-chain RPCs.

## Security

- Passwords: bcrypt, min 10 chars with letter + number
- JWT + optional HttpOnly cookies (`COOKIE_*` env)
- Rate limits on login, register, OTP, password, wallet export
- Wallet export requires password re-auth (`POST /auth/export-wallet`)
- No self-registration as admin
- Production: OpenAPI docs off when `ENVIRONMENT=production`
- Security headers middleware; generic 500s in production
- Never log private keys or OTP codes
- `.env` is gitignored — use `.env.sample` only

Sensitive scripts that hard-coded keys were removed.

## Database Models

See **ARCHITECTURE.md** for full model documentation:

- **User** — investor / fund_manager / admin  
- **UserWallet** — multi-chain addresses  
- **Project** — investment products  
- **Investment** — capital positions  
- **Organization** — fund issuer profiles  

## Testing

```bash
pytest
pytest --cov=api --cov-report=html
pytest -v --asyncio-mode=auto
```

## Database Migrations

### Create new migration
```bash
alembic revision --autogenerate -m "migration description"
```

### Apply migrations
```bash
alembic upgrade head
```

### Downgrade
```bash
alembic downgrade -1
```

## Deployment

### Production Docker Setup
```bash
docker-compose -f docker-compose.prod.yml up --build
```

### Environment Variables for Production
Ensure all required environment variables are set in your production environment, including:
- Database credentials
- Hedera network configuration
- JWT secret keys
- CORS origins

## Development Workflow

### Code Quality
```bash
# Format code
black .

# Sort imports
isort .

# Lint code
flake8 .
pylint api/

# Type checking (if configured)
mypy api/
```

### Pre-commit Hooks
```bash
pre-commit install
pre-commit run --all-files
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Set up development environment with Docker:
   ```bash
   docker-compose up -d db redis
   pip install -r requirements.txt
   ```
4. Make your changes following the code quality standards
5. Add comprehensive tests for new features
6. Ensure all tests pass: `pytest --cov=api --cov-report=html`
7. Update documentation if needed
8. Commit your changes (`git commit -m 'Add amazing feature'`)
9. Push to the branch (`git push origin feature/amazing-feature`)
10. Open a Pull Request

### Code Standards
- **Black**: Code formatting
- **isort**: Import sorting
- **flake8**: Linting
- **pylint**: Static analysis
- **pytest**: Testing with async support
- **pre-commit**: Automated code quality checks

## License

This project is licensed under the terms specified in the LICENSE file.

## Support

For support and questions, please open an issue on the GitHub repository.
