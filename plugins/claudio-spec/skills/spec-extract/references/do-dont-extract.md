> Reference for: Spec Extract
> Load when: Phase 3 (Analysis) — avoiding common extraction mistakes

# Extraction: Do & Don't

Common mistakes when extracting rules from code, with corrections. Load alongside `classification-guide.md` during Phase 3.

---

## Classification Mistakes

### Don't: Treat authorization as infrastructure

```
SKIP: if (user.canApprove?) — infrastructure check
```

**Why it's wrong:** Authorization checks ARE business rules — they define who can do what. `canApprove?` encodes a domain constraint about roles and permissions.

### Do: Extract authorization as a Business Rule or Constraint

```
R-4: Only users with approval rights can approve orders
- Type: Constraint
- Source: src/orders/approve.ts:12
```

---

### Don't: Classify everything in an `if` as a rule

```
R-1: User existence check
- Type: Validation
- Code: if (!user) return null
```

**Why it's wrong:** Null/undefined guards are defensive programming, not business rules. They don't encode domain logic — they prevent crashes.

### Do: Skip null guards, focus on domain conditions

Only classify conditions that would change if business policy changed.

---

### Don't: Ignore test files

```
Cluster: calculateDiscount(), applyPromo(), validateOrder()
(skipped tests/pricing.test.ts)
```

**Why it's wrong:** Test assertions often encode rules more explicitly than production code: `expect(discount).toBe(0.20)` confirms the 20% rate that may be buried in a constant.

### Do: Include test assertions as rule evidence

Use test files to confirm or discover rules. Reference them in the rule's Source field when the test is more explicit than the code.

---

### Don't: Fabricate a rule from user claims

```
R-8: Maximum order amount is $10,000
- Source: (not found in code)
- Description: User mentioned this rule exists
```

**Why it's wrong:** If the code doesn't enforce it, it's not an extracted rule. It may be an intended-but-missing rule — document it as an Open Question, not a confirmed rule.

### Do: Flag missing rules in Open Questions

```
## Open Questions
- [ ] User expects a max order amount of $10,000 but no such check was found
  in the code — intentionally missing or implemented elsewhere?
```

---

## Confidence Mistakes

### Don't: Assign high confidence to magic numbers

```
R-3: Limit is 5
- Confidence: high
- Code: if (count > 5)
```

**Why it's wrong:** `5` has no domain naming. It could be arbitrary, a performance knob, or a real business limit. Without a named constant or comment, confidence should be medium at best.

### Do: Downgrade confidence for unnamed values

```
R-3: Possible limit of 5 on count
- Confidence: medium
- Open Question: Is 5 a business limit or arbitrary threshold?
```

---

### Don't: Mark everything as low confidence to be "safe"

```
R-1: Free shipping over $100 — Confidence: low
R-2: VIP gets 20% discount — Confidence: low
```

**Why it's wrong:** When domain naming is clear (`FREE_SHIPPING_MINIMUM`, `isVip`), low confidence undersells the extraction quality and makes the catalog less useful.

### Do: Trust clear domain naming

If the code uses named constants with business meaning AND the pattern is recognizable, that's high confidence.

---

## Scope Mistakes

### Don't: Extract infrastructure patterns as rules

```
R-5: Cache TTL is 300 seconds
- Type: Constraint
- Code: cache.set(key, value, { ttl: 300 })
```

**Why it's wrong:** Cache TTL is a performance tuning parameter, not a business rule. Changing it doesn't change business behavior — it changes performance.

### Do: Ask "would a product manager care?"

If changing the value would require a business decision (not just a performance review), it's a rule. If it's purely technical — skip it.

---

### Don't: Treat ORM queries as rules

```
R-6: Only active users are queried
- Code: User.where(active: true)
```

**Why it's wrong:** The query filter is a data access pattern. The rule is WHY only active users are queried. What makes a user "active"? That definition is the business rule.

### Do: Extract the definition, not the filter

```
R-6: Inactive users are excluded from order processing
- Description: Users with active=false are filtered out. The definition of
  "active" appears to be: not deleted AND has logged in within 90 days.
- Open Question: Is the 90-day threshold a business policy or arbitrary?
```

---

## Output Mistakes

### Don't: Name rules by code structure

```
R-1: Discount logic
R-2: Validation function
R-3: Status update
```

**Why it's wrong:** These are topics, not rules. A product manager can't understand what the system does from these names.

### Do: Name rules as business policy statements

```
R-1: VIP customers get 20% discount on orders over $100
R-2: Email must be verified before placing an order
R-3: Order moves from pending to confirmed after payment
```

---

### Don't: Copy entire functions as code snippets

```
- Code:
  function processOrder(order) {
    logger.info('processing');
    validateOrder(order);
    const discount = calculateDiscount(order);
    const tax = calculateTax(order);
    // ... 30 more lines
  }
```

**Why it's wrong:** The rule is in one branch or condition — the rest is noise.

### Do: Extract only the decision logic

```
- Code:
  if (order.customer.isVip && order.total > 100) {
    return order.total * 0.80;
  }
```
