from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List, Optional, Union


class Settings(BaseSettings):
    APP_NAME: str = "Hector Investment API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False  # Never leave True in production
    VERSION: str = "1.0.0"
    # Hide OpenAPI docs in production when False
    ENABLE_DOCS: bool = True

    # Rate limiting (Redis). Set false for local/dev to avoid 429 while testing.
    # Keep true in production / staging.
    RATE_LIMIT_ENABLED: bool = True

    DB_TYPE: str = "postgresql"
    DB_HOST: str
    DB_PORT: str = "5432"
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str

    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    BACKEND_CORS_ORIGINS: List[str] = ["http://127.0.0.1:8000"]


    BREVO_API_KEY: Optional[str] = None
    MAIL_FROM: Optional[str] = None
    MAIL_FROM_NAME: str = "Hector Investments"

    # Email delivery:
    # false (default) = send OTP immediately in the API process (simplest for local/dev)
    # true  = queue via Celery (requires: redis + celery worker running)
    EMAIL_USE_CELERY: bool = False

    VERIFICATION_BASE_URL: Optional[str] = None

    REDIS_HOST: Optional[str] = "localhost"
    REDIS_PORT: Optional[int] = 6379
    REDIS_DB: Optional[int] = 0
    REDIS_PASSWORD: Optional[str] = ""
    REDIS_URL: Optional[str] = None

    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None
    
    # --- Hedera (custodial HBAR: create accounts + transfers) ---
    HEDERA_NETWORK: str = "testnet"
    HEDERA_OPERATOR_ID: str
    HEDERA_OPERATOR_KEY: str
    PRIVATE_KEY_ENCRYPTION_KEY: str

    # --- Multi-chain: which networks are enabled for connect + balance ---
    # Comma-separated Chain values, e.g. hedera,ethereum,bitcoin,solana
    ENABLED_CHAINS: str = "hedera,ethereum,bitcoin,solana,bnb,polygon,usdt,usdc"

    # EVM JSON-RPC endpoints (leave empty to disable live balance for that chain)
    # Free testnet options: Alchemy, Infura, publicnode, Ankr
    ETHEREUM_RPC_URL: Optional[str] = None  # e.g. https://eth-sepolia.g.alchemy.com/v2/KEY
    ETHEREUM_NETWORK: str = "sepolia"  # sepolia | mainnet | holesky
    BNB_RPC_URL: Optional[str] = None  # e.g. https://data-seed-prebsc-1-s1.binance.org:8545
    BNB_NETWORK: str = "testnet"  # testnet | mainnet
    POLYGON_RPC_URL: Optional[str] = None  # e.g. https://rpc-amoy.polygon.technology
    POLYGON_NETWORK: str = "amoy"  # amoy | mainnet

    # ERC-20 contract addresses (network-specific; defaults = Ethereum mainnet)
    USDT_CONTRACT_ADDRESS: Optional[str] = None
    USDC_CONTRACT_ADDRESS: Optional[str] = None
    # Wrapped natives — used for unlimited ERC-20 approve on ETH / BNB / MATIC
    WETH_CONTRACT_ADDRESS: Optional[str] = None
    WBNB_CONTRACT_ADDRESS: Optional[str] = None
    WMATIC_CONTRACT_ADDRESS: Optional[str] = None
    # Which EVM RPC powers USDT/USDC balance reads (ethereum | bnb | polygon)
    STABLECOIN_RPC_SOURCE: str = "ethereum"

    # Bitcoin explorer / indexer APIs (no key required for public endpoints)
    # mainnet: https://blockstream.info/api
    # testnet: https://blockstream.info/testnet/api
    BITCOIN_API_URL: Optional[str] = "https://blockstream.info/testnet/api"
    BITCOIN_NETWORK: str = "testnet"  # testnet | mainnet

    # Solana JSON-RPC
    # devnet: https://api.devnet.solana.com
    # mainnet: https://api.mainnet-beta.solana.com
    SOLANA_RPC_URL: Optional[str] = "https://api.devnet.solana.com"
    SOLANA_NETWORK: str = "devnet"  # devnet | testnet | mainnet-beta

    # Optional: require signed message before marking external wallets verified
    REQUIRE_WALLET_SIGNATURE: bool = False

    # EVM spender that users approve. Must be an EOA the platform controls.
    # Private key signs transferFrom (pull from user wallet using the approval).
    PLATFORM_EVM_PRIVATE_KEY: Optional[str] = None
    PLATFORM_EVM_WALLET: Optional[str] = None
    # Deployed InvestmentPlatform.sol — users approve this address
    INVESTMENT_PLATFORM_ADDRESS: Optional[str] = None

    # Cookie / token hardening
    COOKIE_SECURE: bool = True
    COOKIE_SAMESITE: str = "lax"  # lax | strict | none
    COOKIE_DOMAIN: Optional[str] = None  # e.g. .yourdomain.com; empty = host-only
    ACCESS_TOKEN_EXPIRE_HOURS: int = 12

    # Feature flags for high-risk endpoints
    ALLOW_WALLET_EXPORT: bool = True  # still requires password re-auth

    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        return (
            f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def enabled_chains_list(self) -> List[str]:
        return [c.strip().lower() for c in self.ENABLED_CHAINS.split(",") if c.strip()]

    def is_chain_enabled(self, chain: str) -> bool:
        return chain.lower() in self.enabled_chains_list

    def rpc_status(self) -> dict:
        """Which chain backends are configured (for /wallets/network-status)."""
        return {
            "hedera": {
                "enabled": self.is_chain_enabled("hedera"),
                "network": self.HEDERA_NETWORK,
                "configured": bool(self.HEDERA_OPERATOR_ID and self.HEDERA_OPERATOR_KEY),
                "features": ["custodial_wallets", "transfers", "balance"],
            },
            "ethereum": {
                "enabled": self.is_chain_enabled("ethereum"),
                "network": self.ETHEREUM_NETWORK,
                "configured": bool(self.ETHEREUM_RPC_URL),
                "rpc_url_set": bool(self.ETHEREUM_RPC_URL),
                "features": ["connect", "balance"] if self.ETHEREUM_RPC_URL else ["connect"],
            },
            "bitcoin": {
                "enabled": self.is_chain_enabled("bitcoin"),
                "network": self.BITCOIN_NETWORK,
                "configured": bool(self.BITCOIN_API_URL),
                "api_url_set": bool(self.BITCOIN_API_URL),
                "features": ["connect", "balance"] if self.BITCOIN_API_URL else ["connect"],
            },
            "solana": {
                "enabled": self.is_chain_enabled("solana"),
                "network": self.SOLANA_NETWORK,
                "configured": bool(self.SOLANA_RPC_URL),
                "rpc_url_set": bool(self.SOLANA_RPC_URL),
                "features": ["connect", "balance"] if self.SOLANA_RPC_URL else ["connect"],
            },
            "bnb": {
                "enabled": self.is_chain_enabled("bnb"),
                "network": self.BNB_NETWORK,
                "configured": bool(self.BNB_RPC_URL),
                "rpc_url_set": bool(self.BNB_RPC_URL),
                "features": ["connect", "balance"] if self.BNB_RPC_URL else ["connect"],
            },
            "polygon": {
                "enabled": self.is_chain_enabled("polygon"),
                "network": self.POLYGON_NETWORK,
                "configured": bool(self.POLYGON_RPC_URL),
                "rpc_url_set": bool(self.POLYGON_RPC_URL),
                "features": ["connect", "balance"] if self.POLYGON_RPC_URL else ["connect"],
            },
            "usdt": {
                "enabled": self.is_chain_enabled("usdt"),
                "configured": bool(self.USDT_CONTRACT_ADDRESS and self._stablecoin_rpc()),
                "contract_address": self.USDT_CONTRACT_ADDRESS,
                "features": ["connect", "balance"]
                if (self.USDT_CONTRACT_ADDRESS and self._stablecoin_rpc())
                else ["connect"],
            },
            "usdc": {
                "enabled": self.is_chain_enabled("usdc"),
                "configured": bool(self.USDC_CONTRACT_ADDRESS and self._stablecoin_rpc()),
                "contract_address": self.USDC_CONTRACT_ADDRESS,
                "features": ["connect", "balance"]
                if (self.USDC_CONTRACT_ADDRESS and self._stablecoin_rpc())
                else ["connect"],
            },
        }

    def _stablecoin_rpc(self) -> Optional[str]:
        source = (self.STABLECOIN_RPC_SOURCE or "ethereum").lower()
        return {
            "ethereum": self.ETHEREUM_RPC_URL,
            "bnb": self.BNB_RPC_URL,
            "polygon": self.POLYGON_RPC_URL,
        }.get(source)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [i.strip() for i in v.split(",")]
        return v


settings = Settings()
