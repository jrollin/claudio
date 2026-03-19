> Reference for: Spec Extract
> Load when: Phase 3 (Analysis) — classifying decision points into rule types

# Classification Guide: Business Rules vs Infrastructure

How to distinguish intentional domain logic from incidental implementation. Load this during Phase 3 when reading source code and classifying decision points.

---

## Rule Type Decision Tree

When you encounter a decision point (if/else, switch, guard, early return, ternary):

```
Is it about domain concepts (money, users, orders, dates, permissions)?
├── YES → Likely a rule. Which kind?
│   ├── Guards input shape/format? → Validation
│   ├── Computes a value from inputs? → Derived Value
│   ├── Changes entity status/lifecycle? → State Transition
│   ├── Enforces a limit or invariant? → Constraint
│   ├── Provides a default when nothing matches? → Fallback
│   └── None of the above but domain-meaningful? → Business Rule
└── NO → Likely infrastructure. Skip unless it encodes hidden domain logic.
```

---

## Recognizing Business Rules

### Strong signals (high confidence)

- Domain nouns in the condition: `if (order.total > FREE_SHIPPING_THRESHOLD)`
- Named constants with business meaning: `MAX_ACTIVE_SUBSCRIPTIONS`, `TRIAL_PERIOD_DAYS`
- Comments referencing business requirements, tickets, or stakeholders
- Error messages aimed at end users: `"You cannot have more than 5 active plans"`
- Conditional logic that would change if business policy changed

### Weak signals (medium confidence)

- Generic variable names but domain-shaped logic: `if (amount > limit)`
- Logic that looks like a workaround: `if (type === 'legacy')` with no explanation
- Hardcoded values without named constants: `if (count > 5)`
- Conditions that mix domain and infrastructure: `if (user.isActive && cache.has(key))`

### Not rules (skip)

- Null/undefined checks for safety: `if (!user) return`
- Error handling for infrastructure: `try/catch` around HTTP calls
- Logging, metrics, tracing: `logger.info(...)`, `metrics.increment(...)`
- Cache management: `if (cache.expired)` → refresh
- Retry/circuit-breaker logic
- Framework boilerplate: middleware registration, route setup, DI wiring

---

## Recognizing Hidden Rules

Some business rules don't look like rules at first glance:

### Magic numbers

```typescript
// Looks like infrastructure
if (items.length > 50) { paginate() }
```
Ask: Is 50 a business limit (max items per order) or a performance tuning knob? If removing it would change user-facing behavior → it's a rule.

### Implicit defaults

```ruby
def tax_rate
  country_rates[country] || 0.0
end
```
The `|| 0.0` is a Fallback rule: "default tax rate is 0% for unknown countries." These are easy to miss.

### Ordering and priority

```python
if user.is_vip:
    discount = 0.20
elif user.has_coupon:
    discount = coupon.value
else:
    discount = 0
```
The order itself is a rule: "VIP discount takes priority over coupons." Document the priority chain, not just individual branches.

### Negations and exclusions

```java
if (!order.isGift() && !order.isInternal()) {
    applyTax(order);
}
```
Two rules here: "Gift orders are tax-exempt" AND "Internal orders are tax-exempt." Negations often hide domain exceptions.

### Temporal logic

```typescript
if (subscription.createdAt > cutoffDate) { applyNewPricing() }
else { applyLegacyPricing() }
```
This is a State Transition or Business Rule about pricing migration. The cutoff date itself is a rule.

### Configuration-as-rules

```yaml
# config/limits.yml
max_team_members: 25
trial_days: 14
```
Config files often encode business rules. If changing a value would change business behavior → it's a rule, even if it lives outside code.

---

## Compound Conditions

Real legacy code often packs multiple rules into one condition:

```typescript
if (user.isVip && order.total > 100 && !order.isGift) {
  applyDiscount(order, 0.20);
}
```

This single `if` contains **three** distinct business concepts:
1. **R-1: VIP eligibility** — only VIP customers qualify (Business Rule)
2. **R-2: Minimum order threshold** — order must exceed $100 (Constraint)
3. **R-3: Gift exclusion** — gift orders are excluded from discounts (Business Rule)

**How to handle:**
- Split each distinct business concept into its own rule (R-1, R-2, R-3)
- Note dependencies: "R-1, R-2, R-3 are combined in a single condition — all must be true for the discount to apply"
- Document the priority/conjunction: AND means all required, OR means alternatives
- The code snippet can be shared across related rules, but each rule's Description should focus on its own concept

**Watch for implicit rules in the combination order:**
```python
if is_employee or (is_vip and order.total > 50):
```
Here, employees get the discount unconditionally (no minimum), but VIPs need $50+. The OR branch creates two different rule paths with different constraints.

---

## Confidence Assessment

| Confidence | Criteria | Example |
|------------|----------|---------|
| **high** | Clear domain naming + recognizable business pattern + tests or comments confirm intent | `if (order.total >= FREE_SHIPPING_MINIMUM)` with a test "orders over $100 ship free" |
| **medium** | Readable logic but generic names, OR domain-shaped but could be a bug/workaround | `if (count > 5)` where 5 might be a business limit or arbitrary |
| **low** | Obscure logic, magic numbers, no naming hints, contradicts other rules, or dead code path that still executes | `if (x & 0x04)` in a billing module |

When in doubt, classify as **medium** and add to Open Questions.

---

## Common Misclassifications

| Mistake | Reality |
|---------|---------|
| Treating all `if` statements as rules | Many are null checks, error handling, or flow control |
| Treating ORM/query logic as rules | `where(active: true)` is a filter, not a rule — unless the definition of "active" encodes business logic |
| Treating authorization checks as infrastructure | `if (user.canApprove?)` IS a business rule — it defines who can do what |
| Treating error messages as infrastructure | User-facing error messages often describe business constraints in plain English |
| Ignoring test files | Test assertions like `expect(discount).to eq(0.20)` confirm and sometimes reveal rules not obvious in production code |
