import asyncio
from typing import Optional
from hiero_sdk_python import Client, AccountId, PrivateKey, Hbar, AccountCreateTransaction, AccountInfoQuery, Network, TransferTransaction, TransactionGetReceiptQuery, CryptoGetAccountBalanceQuery
from api.utils.settings import settings
from api.v1.models.project import Project
from api.v1.models.investment import Investment
from sqlalchemy.orm import Session
import requests
from uuid import UUID
import logging
import time
import os
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import base64

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def get_hedera_client() -> Client:
    """
    Get configured Hedera client for testnet or mainnet.
    """
    try:
        network = settings.HEDERA_NETWORK.lower()
        client = Client(Network(network='testnet' if network == 'testnet' else 'mainnet'))
        
        account_id = AccountId.from_string(settings.HEDERA_OPERATOR_ID)
        operator_key = PrivateKey.from_string(settings.HEDERA_OPERATOR_KEY)
        
        client.set_operator(account_id, operator_key)
        logger.info("Hedera client initialized for network=%s", network)
        return client
        
    except ValueError as e:
        logger.error(f"Invalid Hedera configuration: {str(e)}")
        raise ValueError(f"Invalid Hedera configuration: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error in get_hedera_client: {type(e).__name__}: {str(e)}")
        raise ValueError(f"Failed to initialize Hedera client: {type(e).__name__}: {str(e)}")
    

async def create_user_wallet() -> tuple[str, str]:
    """
    Create a new Hedera account for a user and return (wallet_address, encrypted_private_key)
    """
    client = await get_hedera_client()
    loop = asyncio.get_event_loop()

    def sync_create_account():
        try:
            new_key = PrivateKey.generate("ecdsa")
            private_key_string = new_key.to_string()  
            
            logger.debug(f"Generating new ECDSA account for user with public key: {new_key.public_key()}")

            operator_key = PrivateKey.from_string(settings.HEDERA_OPERATOR_KEY)

            transaction = (
                AccountCreateTransaction()
                .set_key(new_key.public_key())
                .set_initial_balance(Hbar(1))
                .set_account_memo("User investment wallet")
                .freeze_with(client)
                .sign(operator_key)
            )

            receipt = transaction.execute(client)
            logger.debug(f"User wallet transaction submitted: {receipt.transaction_id}")

            if receipt.status != 22:
                raise ValueError(f"User wallet creation failed with status: {receipt.status}")

            if receipt.account_id is None:
                raise ValueError("Account ID not found in receipt")

            account_id = str(receipt.account_id)
            logger.info(f"Successfully created user Hedera account: {account_id}")
            
            return account_id, private_key_string

        except Exception as e:
            logger.error(f"Failed to create user Hedera account: {type(e).__name__}: {str(e)}")
            raise

    return await loop.run_in_executor(None, sync_create_account)

def encrypt_private_key(private_key: str, encryption_key: str) -> str:
    """
    Encrypt a private key using Fernet symmetric encryption.
    """
    f = Fernet(encryption_key)
    encrypted_key = f.encrypt(private_key.encode())
    return encrypted_key.decode()

def decrypt_private_key(encrypted_key: str, encryption_key: str) -> str:
    """
    Decrypt a private key.
    """
    f = Fernet(encryption_key)
    decrypted_key = f.decrypt(encrypted_key.encode())
    return decrypted_key.decode()


async def get_wallet_balance(wallet_address: str) -> float:
    """
    Get the HBAR balance of a wallet using the correct pattern from docs.
    """
    client = await get_hedera_client()
    loop = asyncio.get_event_loop()

    def sync_get_balance():
        try:
            account_id = AccountId.from_string(wallet_address)
            balance_query = CryptoGetAccountBalanceQuery().set_account_id(account_id)
            balance_result = balance_query.execute(client)
            
            balance_hbar = balance_result.hbars.to_hbars()
            logger.debug(f"Balance for {wallet_address}: {balance_hbar} HBAR")
            return float(balance_hbar)
            
        except Exception as e:
            logger.error(f"Failed to get balance for {wallet_address}: {str(e)}")
            return 0.0

    balance = await loop.run_in_executor(None, sync_get_balance)
    return balance

async def create_project_wallet(db: Session, project: Optional[Project] = None) -> str:
    """
    Create a new Hedera account for a project wallet.
    """
    client = await get_hedera_client()
    loop = asyncio.get_event_loop()

    def sync_create_account():
        try:
            new_key = PrivateKey.generate("ecdsa")
            logger.debug(f"Generating new ECDSA account with public key: {new_key.public_key()}")

            operator_key = PrivateKey.from_string(settings.HEDERA_OPERATOR_KEY)

            transaction = (
                AccountCreateTransaction()
                .set_key(new_key.public_key())
                .set_initial_balance(Hbar(1))
                .set_account_memo("Product treasury wallet")
                .freeze_with(client)
                .sign(operator_key)
            )

            receipt = transaction.execute(client)
            logger.debug(f"Transaction submitted: {receipt.transaction_id}")
            logger.debug(f"Transaction receipt status: {receipt.status}")

            # Check if account was created successfully
            if receipt.account_id is None:
                raise ValueError(f"Account creation failed. Status code: {receipt.status}")

            account_id = str(receipt.account_id)
            logger.info(f"Successfully created Hedera account: {account_id}")
            return account_id

        except Exception as e:
            logger.error(f"Failed to create Hedera account: {type(e).__name__}: {str(e)}")
            raise

    try:
        account_id = await loop.run_in_executor(None, sync_create_account)
        if project:
            project.wallet_address = account_id
            db.commit()
        return account_id
    except Exception as e:
        logger.error(f"Failed to create Hedera wallet: {type(e).__name__}: {str(e)}")
        raise ValueError(f"Failed to create Hedera wallet: {type(e).__name__}: {str(e)}")
        

async def transfer_hbar_to_treasury(investor_wallet: str, project_wallet: str, amount_hbar: float, investor_private_key: str) -> str:
    """
    Transfer HBAR from investor wallet to product treasury.
    """
    client = await get_hedera_client()
    loop = asyncio.get_event_loop()

    def sync_transfer():
        try:
            investor_account = AccountId.from_string(investor_wallet)
            project_id = AccountId.from_string(project_wallet)
            investor_key = PrivateKey.from_string(investor_private_key)

            logger.debug(f"Processing investment transfer: {amount_hbar} HBAR from {investor_wallet} to {project_wallet}")

            amount_tinybars = int(amount_hbar * 100_000_000)
            
            transaction = (
                TransferTransaction()
                .add_hbar_transfer(investor_account, -amount_tinybars)
                .add_hbar_transfer(project_id, amount_tinybars)
                .freeze_with(client)
                .sign(investor_key)
            )

            receipt = transaction.execute(client)
            transaction_id = transaction.transaction_id
            
            logger.debug(f"Transaction ID: {transaction_id}")
            logger.debug(f"Transaction status: {receipt.status}")

            if receipt.status != 22:  # SUCCESS
                raise ValueError(f"Transaction failed with status: {receipt.status}")

            tx_str = str(transaction_id)
            # Format 1: Replace @ with -
            tx_hash = tx_str.replace('@', '-')
            # Format 2: If that doesn't work, we'll try the original in verify_transaction
            
            logger.info(f"Investment transfer completed successfully: {tx_hash}")
            return tx_hash

        except Exception as e:
            logger.error(f"Failed to process investment transfer: {type(e).__name__}: {str(e)}")
            raise

    tx_hash = await loop.run_in_executor(None, sync_transfer)
    return tx_hash

async def invest_hbar_from_user(user_id: UUID, project_wallet: str, amount_hbar: float, db: Session) -> str:
    """
    Process an HBAR investment transfer using the user's custodial private key.
    """
    client = await get_hedera_client()
    loop = asyncio.get_event_loop()

    def sync_transfer():
        try:
            from api.v1.models.user import User
            user = db.query(User).filter(User.id == user_id).first()
            if not user or not user.wallet_address or not user.encrypted_private_key:
                raise ValueError("User wallet not found or not properly configured")

            investor_account = AccountId.from_string(user.wallet_address)
            project_id = AccountId.from_string(project_wallet)

            logger.debug(f"Processing investment transfer: {amount_hbar} HBAR from {user.wallet_address} to {project_wallet}")

            amount_tinybars = int(amount_hbar * 100_000_000)
            
            investor_private_key_str = decrypt_private_key(user.encrypted_private_key, settings.PRIVATE_KEY_ENCRYPTION_KEY)
            
            investor_key = PrivateKey.from_string_ecdsa(investor_private_key_str)
            logger.debug(f"Using ECDSA key for investment transfer: {investor_key.public_key()}")

            transaction = (
                TransferTransaction()
                .add_hbar_transfer(investor_account, -amount_tinybars)
                .add_hbar_transfer(project_id, amount_tinybars)
                .freeze_with(client)
                .sign(investor_key)
            )

            receipt = transaction.execute(client)
            transaction_id = transaction.transaction_id
            
            logger.debug(f"Transaction ID: {transaction_id}")
            logger.debug(f"Transaction status: {receipt.status}")

            if receipt.status != 22:
                raise ValueError(f"Transaction failed with status: {receipt.status}")

            tx_hash = str(transaction_id).replace('@', '-')
            logger.info(f"Investment transfer completed successfully: {tx_hash}")
            return tx_hash

        except Exception as e:
            logger.error(f"Failed to process investment transfer: {type(e).__name__}: {str(e)}")
            raise

    tx_hash = await loop.run_in_executor(None, sync_transfer)
    return tx_hash

async def transfer_hbar_p2p(sender_user_id: UUID, recipient_wallet: str, amount_hbar: float, db: Session, memo: str = "P2P transfer") -> str:
    """
    Transfer HBAR between user wallets (P2P transfer).
    """
    client = await get_hedera_client()
    loop = asyncio.get_event_loop()

    def sync_transfer():
        try:
            from api.v1.models.user import User
            sender = db.query(User).filter(User.id == sender_user_id).first()
            if not sender or not sender.wallet_address or not sender.encrypted_private_key:
                raise ValueError("Sender wallet not found or not properly configured")

            sender_id = AccountId.from_string(sender.wallet_address)
            recipient_id = AccountId.from_string(recipient_wallet)

            logger.debug(f"Processing P2P transfer: {amount_hbar} HBAR from {sender.wallet_address} to {recipient_wallet}")

            amount_tinybars = int(amount_hbar * 100_000_000)
            
            investor_private_key_str = decrypt_private_key(sender.encrypted_private_key, settings.PRIVATE_KEY_ENCRYPTION_KEY)
            
            # Try different key loading methods
            try:
                # Method 1: Try ECDSA explicitly first
                investor_key = PrivateKey.from_string_ecdsa(investor_private_key_str)
                logger.debug("Successfully loaded as ECDSA key")
            except Exception as e1:
                logger.debug(f"ECDSA loading failed: {e1}, trying general method")
                try:
                    # Method 2: Try general method
                    investor_key = PrivateKey.from_string(investor_private_key_str)
                    logger.debug("Successfully loaded with general method")
                except Exception as e2:
                    logger.debug(f"General method failed: {e2}, trying from bytes")
                    try:
                        # Method 3: Try from bytes
                        key_bytes = bytes.fromhex(investor_private_key_str)
                        investor_key = PrivateKey.from_bytes_ecdsa(key_bytes)
                        logger.debug("Successfully loaded from bytes")
                    except Exception as e3:
                        logger.error(f"All key loading methods failed: {e3}")
                        raise ValueError(f"Failed to load private key: {e3}")

            logger.debug(f"Using key for P2P transfer: {investor_key.public_key()}")

            transaction = (
                TransferTransaction()
                .add_hbar_transfer(sender_id, -amount_tinybars)
                .add_hbar_transfer(recipient_id, amount_tinybars)
                .set_transaction_memo(memo)
                .freeze_with(client)
                .sign(investor_key)
            )

            # Execute transaction
            receipt = transaction.execute(client)
            transaction_id = transaction.transaction_id
            
            logger.debug(f"P2P Transaction ID: {transaction_id}")
            logger.debug(f"P2P Transaction status: {receipt.status}")

            if receipt.status != 22:
                raise ValueError(f"P2P transfer failed with status: {receipt.status}")

            tx_hash = str(transaction_id).replace('@', '-')
            logger.info(f"P2P transfer completed successfully: {tx_hash}")
            return tx_hash

        except Exception as e:
            logger.error(f"Failed to process P2P transfer: {type(e).__name__}: {str(e)}")
            raise

    tx_hash = await loop.run_in_executor(None, sync_transfer)
    return tx_hash

async def verify_transaction(tx_hash: str) -> dict:
    """
    Verify a transaction using Hedera Mirror Node API.
    Try multiple transaction ID formats.
    """
    import httpx
    import asyncio
    
    network = settings.HEDERA_NETWORK.lower()
    mirror_node_url = f"https://{'testnet' if network == 'testnet' else 'mainnet'}.mirrornode.hedera.com"
    
    await asyncio.sleep(5)
    
    # Try multiple transaction ID formats
    formats_to_try = [
        tx_hash,  # Original format with -
        tx_hash.replace('-', '@'),  # Replace - with @
        tx_hash.split('-')[0] + '@' + tx_hash.split('-')[1].split('.')[0] + '.' + tx_hash.split('-')[1].split('.')[1][:6],  # Limited precision
    ]
    
    max_retries = 3
    for tx_format in formats_to_try:
        for attempt in range(max_retries):
            try:
                url = f"{mirror_node_url}/api/v1/transactions/{tx_format}"
                logger.debug(f"Verifying transaction attempt {attempt + 1} with format: {tx_format}")
                
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url)
                    
                    if response.status_code == 200:
                        result = response.json()
                        transactions = result.get("transactions", [])
                        if not transactions:
                            continue
                        
                        tx = transactions[0]
                        transfers = tx.get("transfers", [])
                        
                        # Find the transfer amounts
                        positive_transfers = [t for t in transfers if t.get("amount", 0) > 0]
                        negative_transfers = [t for t in transfers if t.get("amount", 0) < 0]
                        
                        return {
                            "valid": tx.get("result") == "SUCCESS",
                            "amount": sum(t.get("amount", 0) for t in positive_transfers) / 100_000_000,
                            "from_account": negative_transfers[0].get("account") if negative_transfers else None,
                            "to_account": positive_transfers[0].get("account") if positive_transfers else None,
                            "timestamp": tx.get("consensus_timestamp"),
                            "transaction_id": tx.get("transaction_id"),
                            "transfers": transfers
                        }
                    elif response.status_code == 404:
                        # Transaction not yet indexed, wait and retry
                        if attempt < max_retries - 1:
                            wait_time = 2 ** attempt
                            logger.debug(f"Transaction not indexed yet with format {tx_format}, waiting {wait_time}s...")
                            await asyncio.sleep(wait_time)
                            continue
                    else:
                        # Other HTTP error, try next format
                        break
                        
            except Exception as e:
                logger.debug(f"Failed with format {tx_format} attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
    
    logger.warning(f"Could not verify transaction {tx_hash} with mirror node using any format")
    return {
        "valid": False,
        "amount": 0,
        "from_account": None,
        "to_account": None,
        "timestamp": None,
        "transaction_id": tx_hash,
        "error": "Transaction not found in mirror node after trying multiple formats"
    }

async def trace_transaction(tx_hash: str, db: Session) -> dict:
    """
    Trace an investment settlement by transaction hash.
    
    Args:
        tx_hash: Hedera transaction ID
        db: SQLAlchemy session
    
    Returns:
        dict: Transaction details with linked investment/product
    """
    verification = await verify_transaction(tx_hash)
    investment = db.query(Investment).filter(Investment.tx_hash == tx_hash).first()
    
    result = {
        "transaction_id": tx_hash,
        "valid": verification["valid"],
        "amount": verification["amount"],
        "from_account": verification["from_account"],
        "to_account": verification["to_account"],
        "timestamp": verification["timestamp"]
    }
    
    if investment:
        result.update({
            "investment_id": investment.id,
            "project_id": investment.project_id,
            "investor_id": investment.investor_id,
            "status": investment.status.value,
            "asset_symbol": investment.asset_symbol,
            "asset_chain": investment.asset_chain,
        })
    
    return result

async def update_raised_amount(db: Session, project_id: UUID, amount: float):
    """
    Update product capital raised (amount_raised). Prefer investment.update_product_totals.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        project.amount_raised = (project.amount_raised or 0.0) + amount
        db.commit()