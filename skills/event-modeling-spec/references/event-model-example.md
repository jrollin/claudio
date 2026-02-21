> Reference for: Event Modeling
> Load when: Need a full example of a completed event model document

# Hotel Booking — Event Model

## How to Read This Document

This document describes the system as a **timeline of events** — business facts that happen over time. Everything the system does is captured in **slices**, each representing one feature or use case.

### Building Blocks

| Block | Color | What it is |
|-------|-------|------------|
| **Trigger** | White | What starts a use case: a UI screen, an API endpoint, or an automated process |
| **Command** | Blue | An intention to change system state, with parameters |
| **Event** | Orange | A business fact that happened and was persisted. Past tense, business language |
| **View** | Green | A read-only query that presents data from events for a screen, report, or process |

### Patterns

- **Command** — A user or API triggers a state change: `Trigger → Command → Event(s)`
- **View** — Events are projected into a query result: `Event(s) → View → Trigger`
- **Automation** — The system reacts automatically via a todo-list: `Event(s) → Todo View → 🤖 Robot → Command → Event(s)`
- **Translation** — An external system sends data that we translate: `External Event(s) → View → 🤖 Translator → Command → Event(s)`

### Specifications

- **Commands** use Given-When-Then: what state exists → what action happens → what event is produced
- **Views** use Given-Then: what events exist → what the query returns
- **Automations** use Given-When-Then: what the todo list shows → what the robot calls → what event is produced (row disappears)

---

## Swim Lanes

| Lane | Domain | Description |
|------|--------|-------------|
| Guest | Identity & Loyalty | Registration, profiles, loyalty accounts and rewards |
| Inventory | Rooms | Room catalog, availability |
| Booking | Reservations | Booking lifecycle from initiation to cancellation |
| Payment | Payments | Authorization, capture, refunds |
| Stay | Operations | Check-in, room keys, check-out, occupancy |

---

## Slices

### G-1: RegisterGuest
**Pattern:** Command
**Swim Lane:** Guest

**Trigger:**
- Role: Guest
- UI: `[Registration Form: first name, last name, email, phone, password — "Create Account" button]`
- API: `POST /guests`

**Command (blue):**
```
RegisterGuest {
  firstName: "Alice",
  lastName: "Dupont",
  email: "alice@example.com",
  phone: "+33612345678"
}
```

**Event (orange):**
```
GuestRegistered {
  guestId: "g-001",
  firstName: "Alice",
  lastName: "Dupont",
  email: "alice@example.com",
  phone: "+33612345678",
  registeredAt: "2026-02-21T09:00:00Z"
}
```

**Specification:**
> Given: (no prior events)
> When: RegisterGuest { firstName: "Alice", lastName: "Dupont", email: "alice@example.com", phone: "+33612345678" }
> Then: GuestRegistered { guestId: "g-001", firstName: "Alice", lastName: "Dupont", email: "alice@example.com", registeredAt: "2026-02-21T09:00:00Z" }

---

### G-2: GuestProfile
**Pattern:** View
**Swim Lane:** Guest

**Trigger:**
- Role: Guest
- UI: `[Profile Screen: name, email, phone, loyalty points balance]`
- API: `GET /guests/{guestId}`

**View (green):**
```
GuestProfile {
  guestId: "g-001",
  fullName: "Alice Dupont",
  email: "alice@example.com",
  phone: "+33612345678",
  loyaltyPoints: 350
}
```
Source events: GuestRegistered, LoyaltyPointsEarned, LoyaltyRewardRedeemed

**Specification:**
> Given: GuestRegistered { guestId: "g-001", firstName: "Alice", lastName: "Dupont" }, LoyaltyPointsEarned { guestId: "g-001", points: 350 }
> Then: GuestProfile shows fullName "Alice Dupont", loyaltyPoints 350

---

### G-3: OpenLoyaltyAccount
**Pattern:** Automation
**Swim Lane:** Guest

**Todo-list view:**
```
GuestsWithoutLoyaltyAccount {
  rows: [{ guestId: "g-001", email: "alice@example.com" }]
}
```
Feeds from: GuestRegistered where LoyaltyAccountOpened missing for that guestId

**Robot:** Loyalty Initializer

**Command (blue):**
```
OpenLoyaltyAccount {
  guestId: "g-001",
  tier: "Standard"
}
```

**Event (orange):**
```
LoyaltyAccountOpened {
  guestId: "g-001",
  accountId: "la-001",
  tier: "Standard",
  initialPoints: 0,
  openedAt: "2026-02-21T09:01:00Z"
}
```

**Specification:**
> Given: Todo view "GuestsWithoutLoyaltyAccount" shows [{ guestId: "g-001" }]
> When: Robot calls OpenLoyaltyAccount { guestId: "g-001", tier: "Standard" }
> Then: LoyaltyAccountOpened { guestId: "g-001", accountId: "la-001", tier: "Standard", initialPoints: 0 } — row removed from todo

---

### I-1: AddRoom
**Pattern:** Command
**Swim Lane:** Inventory

**Trigger:**
- Role: Admin (Front Desk Agent)
- UI: `[Room Setup Form: room number, type, capacity, base price, amenities — "Add Room" button]`
- API: `POST /rooms`

**Command (blue):**
```
AddRoom {
  roomNumber: "204",
  type: "Double",
  capacity: 2,
  pricePerNight: 120.00,
  amenities: ["WiFi", "TV", "Minibar"]
}
```

**Event (orange):**
```
RoomAdded {
  roomId: "r-204",
  roomNumber: "204",
  type: "Double",
  capacity: 2,
  pricePerNight: 120.00,
  amenities: ["WiFi", "TV", "Minibar"],
  addedAt: "2026-01-01T08:00:00Z"
}
```

**Specification:**
> Given: (no prior events)
> When: AddRoom { roomNumber: "204", type: "Double", capacity: 2, pricePerNight: 120.00 }
> Then: RoomAdded { roomId: "r-204", roomNumber: "204", type: "Double", pricePerNight: 120.00 }

---

### I-2: RoomAvailability
**Pattern:** View
**Swim Lane:** Inventory

**Trigger:**
- Role: Guest
- UI: `[Search Form: check-in date, check-out date, guests count — "Search" button → Room list with photos, price, amenities]`
- API: `GET /rooms/availability?checkIn=2026-03-10&checkOut=2026-03-12&guests=2`

**View (green):**
```
RoomAvailability {
  checkIn: "2026-03-10",
  checkOut: "2026-03-12",
  availableRooms: [
    { roomId: "r-204", type: "Double", pricePerNight: 120.00, amenities: ["WiFi", "TV", "Minibar"] },
    { roomId: "r-310", type: "Suite", pricePerNight: 250.00, amenities: ["WiFi", "TV", "Jacuzzi"] }
  ]
}
```
Source events: RoomAdded, BookingConfirmed, BookingCancelled

**Specification:**
> Given: RoomAdded { roomId: "r-204" }, RoomAdded { roomId: "r-310" }, BookingConfirmed { roomId: "r-204", checkIn: "2026-03-10", checkOut: "2026-03-12" }
> Then: For dates Mar 10–12: shows r-310 only (r-204 booked). For other dates: shows both.

---

### B-1: InitiateBooking
**Pattern:** Command
**Swim Lane:** Booking

**Trigger:**
- Role: Guest
- UI: `[Room Detail: room summary, date selector, guest count — "Reserve Now" button]`
- API: `POST /bookings`

**Command (blue):**
```
InitiateBooking {
  guestId: "g-001",
  roomId: "r-204",
  checkIn: "2026-03-10",
  checkOut: "2026-03-12",
  guests: 2
}
```

**Event (orange):**
```
BookingInitiated {
  bookingId: "b-9001",
  guestId: "g-001",
  roomId: "r-204",
  checkIn: "2026-03-10",
  checkOut: "2026-03-12",
  guests: 2,
  totalPrice: 240.00,
  status: "Pending",
  initiatedAt: "2026-02-21T10:05:00Z"
}
```

**Specification:**
> Given: GuestRegistered { guestId: "g-001" }, RoomAdded { roomId: "r-204", pricePerNight: 120.00 }
> When: InitiateBooking { guestId: "g-001", roomId: "r-204", checkIn: "2026-03-10", checkOut: "2026-03-12", guests: 2 }
> Then: BookingInitiated { bookingId: "b-9001", totalPrice: 240.00, status: "Pending" }

---

### B-2: ConfirmBooking
**Pattern:** Automation
**Swim Lane:** Booking

**Todo-list view:**
```
BookingsPendingConfirmation {
  rows: [{ bookingId: "b-9001", guestId: "g-001", roomId: "r-204" }]
}
```
Feeds from: PaymentCaptured where BookingConfirmed missing for that bookingId

**Robot:** Booking Confirmer

**Command (blue):**
```
ConfirmBooking {
  bookingId: "b-9001"
}
```

**Event (orange):**
```
BookingConfirmed {
  bookingId: "b-9001",
  guestId: "g-001",
  roomId: "r-204",
  checkIn: "2026-03-10",
  checkOut: "2026-03-12",
  confirmedAt: "2026-02-21T10:07:00Z"
}
```

**Specification:**
> Given: Todo view "BookingsPendingConfirmation" shows [{ bookingId: "b-9001" }]
> When: Robot calls ConfirmBooking { bookingId: "b-9001" }
> Then: BookingConfirmed { bookingId: "b-9001", confirmedAt: "2026-02-21T10:07:00Z" } — row removed from todo

---

### B-3: CancelBooking
**Pattern:** Command
**Swim Lane:** Booking

**Trigger:**
- Role: Guest or Front Desk Agent
- UI: `[Booking Detail: booking summary — "Cancel Booking" button + reason dropdown]`
- API: `DELETE /bookings/{bookingId}`

**Command (blue):**
```
CancelBooking {
  bookingId: "b-9001",
  cancelledBy: "g-001",
  reason: "Change of plans"
}
```

**Event (orange):**
```
BookingCancelled {
  bookingId: "b-9001",
  guestId: "g-001",
  roomId: "r-204",
  cancelledBy: "g-001",
  reason: "Change of plans",
  cancelledAt: "2026-02-22T08:00:00Z"
}
```

**Specification:**
> Given: BookingConfirmed { bookingId: "b-9001", guestId: "g-001", roomId: "r-204" }
> When: CancelBooking { bookingId: "b-9001", cancelledBy: "g-001", reason: "Change of plans" }
> Then: BookingCancelled { bookingId: "b-9001", cancelledAt: "2026-02-22T08:00:00Z" }

---

### B-4: GuestBookings
**Pattern:** View
**Swim Lane:** Booking

**Trigger:**
- Role: Guest
- UI: `[My Bookings: list of bookings with room, dates, status, price]`
- API: `GET /guests/{guestId}/bookings`

**View (green):**
```
GuestBookings {
  guestId: "g-001",
  bookings: [
    { bookingId: "b-9001", roomNumber: "204", checkIn: "2026-03-10", checkOut: "2026-03-12", status: "Confirmed", totalPrice: 240.00 }
  ]
}
```
Source events: BookingInitiated, BookingConfirmed, BookingCancelled, CheckInCompleted, CheckOutCompleted

**Specification:**
> Given: BookingInitiated { bookingId: "b-9001", guestId: "g-001", totalPrice: 240.00 }, BookingConfirmed { bookingId: "b-9001" }
> Then: GuestBookings for g-001 shows b-9001 with status "Confirmed", totalPrice 240.00

---

### P-1: AuthorizePayment
**Pattern:** Command
**Swim Lane:** Payment

**Trigger:**
- Role: Guest
- UI: `[Payment Screen: booking summary, card input (number, expiry, CVV) — "Pay Now" button]`
- API: `POST /payments/authorize`

**Command (blue):**
```
AuthorizePayment {
  bookingId: "b-9001",
  guestId: "g-001",
  amount: 240.00,
  currency: "EUR",
  cardToken: "tok_visa_4242"
}
```

**Event (orange):**
```
PaymentAuthorized {
  paymentId: "pay-7001",
  bookingId: "b-9001",
  guestId: "g-001",
  amount: 240.00,
  currency: "EUR",
  authCode: "AUTH-XYZ",
  authorizedAt: "2026-02-21T10:06:00Z"
}
```

**Specification:**
> Given: BookingInitiated { bookingId: "b-9001", totalPrice: 240.00 }
> When: AuthorizePayment { bookingId: "b-9001", amount: 240.00, currency: "EUR", cardToken: "tok_visa_4242" }
> Then: PaymentAuthorized { paymentId: "pay-7001", bookingId: "b-9001", amount: 240.00, authCode: "AUTH-XYZ" }

---

### P-2: CapturePayment
**Pattern:** Automation
**Swim Lane:** Payment

**Todo-list view:**
```
PaymentsToCapture {
  rows: [{ paymentId: "pay-7001", bookingId: "b-9001", authCode: "AUTH-XYZ", amount: 240.00 }]
}
```
Feeds from: PaymentAuthorized where PaymentCaptured missing for that paymentId

**Robot:** Payment Capturer

**Command (blue):**
```
CapturePayment {
  paymentId: "pay-7001",
  bookingId: "b-9001"
}
```

**Event (orange):**
```
PaymentCaptured {
  paymentId: "pay-7001",
  bookingId: "b-9001",
  amount: 240.00,
  currency: "EUR",
  capturedAt: "2026-02-21T10:06:30Z"
}
```

**Specification:**
> Given: Todo view "PaymentsToCapture" shows [{ paymentId: "pay-7001", bookingId: "b-9001", amount: 240.00 }]
> When: Robot calls CapturePayment { paymentId: "pay-7001", bookingId: "b-9001" }
> Then: PaymentCaptured { paymentId: "pay-7001", amount: 240.00, capturedAt: "2026-02-21T10:06:30Z" } — row removed from todo

---

### P-3: RefundPayment
**Pattern:** Automation
**Swim Lane:** Payment

**Todo-list view:**
```
BookingsCancelledWithPayment {
  rows: [{ bookingId: "b-9001", paymentId: "pay-7001", amount: 240.00 }]
}
```
Feeds from: BookingCancelled where PaymentCaptured exists and PaymentRefunded missing

**Robot:** Refund Processor

**Command (blue):**
```
RefundPayment {
  paymentId: "pay-7001",
  bookingId: "b-9001",
  amount: 240.00,
  reason: "Booking cancelled"
}
```

**Event (orange):**
```
PaymentRefunded {
  paymentId: "pay-7001",
  bookingId: "b-9001",
  amount: 240.00,
  currency: "EUR",
  refundedAt: "2026-02-22T08:05:00Z"
}
```

**Specification:**
> Given: Todo view "BookingsCancelledWithPayment" shows [{ bookingId: "b-9001", paymentId: "pay-7001", amount: 240.00 }]
> When: Robot calls RefundPayment { paymentId: "pay-7001", amount: 240.00 }
> Then: PaymentRefunded { paymentId: "pay-7001", amount: 240.00, refundedAt: "2026-02-22T08:05:00Z" } — row removed from todo

---

### S-1: CheckIn
**Pattern:** Command
**Swim Lane:** Stay

**Trigger:**
- Role: Front Desk Agent
- UI: `[Check-In Terminal: guest search, booking lookup, ID verification checkbox, room assignment — "Complete Check-In" button]`
- API: `POST /stays/check-in`

**Command (blue):**
```
CompleteCheckIn {
  bookingId: "b-9001",
  guestId: "g-001",
  roomId: "r-204",
  checkedInBy: "agent-005",
  idVerified: true
}
```

**Event (orange):**
```
CheckInCompleted {
  stayId: "stay-001",
  bookingId: "b-9001",
  guestId: "g-001",
  roomId: "r-204",
  checkedInAt: "2026-03-10T14:30:00Z",
  checkedInBy: "agent-005"
}
```

**Specification:**
> Given: BookingConfirmed { bookingId: "b-9001", guestId: "g-001", roomId: "r-204" }, PaymentCaptured { bookingId: "b-9001" }
> When: CompleteCheckIn { bookingId: "b-9001", guestId: "g-001", roomId: "r-204", checkedInBy: "agent-005", idVerified: true }
> Then: CheckInCompleted { stayId: "stay-001", bookingId: "b-9001", roomId: "r-204", checkedInAt: "2026-03-10T14:30:00Z" }

---

### S-2: IssueRoomKey
**Pattern:** Automation
**Swim Lane:** Stay

**Todo-list view:**
```
CheckInsWithoutKey {
  rows: [{ stayId: "stay-001", guestId: "g-001", roomId: "r-204" }]
}
```
Feeds from: CheckInCompleted where RoomKeyIssued missing for that stayId

**Robot:** Key Issuer

**Command (blue):**
```
IssueRoomKey {
  stayId: "stay-001",
  roomId: "r-204",
  guestId: "g-001"
}
```

**Event (orange):**
```
RoomKeyIssued {
  stayId: "stay-001",
  roomId: "r-204",
  guestId: "g-001",
  keyCode: "KEY-8824-X",
  issuedAt: "2026-03-10T14:32:00Z"
}
```

**Specification:**
> Given: Todo view "CheckInsWithoutKey" shows [{ stayId: "stay-001", roomId: "r-204" }]
> When: Robot calls IssueRoomKey { stayId: "stay-001", roomId: "r-204", guestId: "g-001" }
> Then: RoomKeyIssued { stayId: "stay-001", keyCode: "KEY-8824-X", issuedAt: "2026-03-10T14:32:00Z" } — row removed from todo

---

### S-3: CheckOut
**Pattern:** Command
**Swim Lane:** Stay

**Trigger:**
- Role: Front Desk Agent or Guest (self-checkout kiosk)
- UI: `[Check-Out Screen: stay summary, outstanding charges — "Confirm Check-Out" button]`
- API: `POST /stays/check-out`

**Command (blue):**
```
CompleteCheckOut {
  stayId: "stay-001",
  guestId: "g-001",
  roomId: "r-204",
  checkedOutBy: "g-001"
}
```

**Event (orange):**
```
CheckOutCompleted {
  stayId: "stay-001",
  bookingId: "b-9001",
  guestId: "g-001",
  roomId: "r-204",
  checkedOutAt: "2026-03-12T11:00:00Z",
  nightsStayed: 2
}
```

**Specification:**
> Given: CheckInCompleted { stayId: "stay-001", guestId: "g-001", roomId: "r-204", checkedInAt: "2026-03-10T14:30:00Z" }
> When: CompleteCheckOut { stayId: "stay-001", guestId: "g-001", roomId: "r-204" }
> Then: CheckOutCompleted { stayId: "stay-001", checkedOutAt: "2026-03-12T11:00:00Z", nightsStayed: 2 }

---

### S-4: RoomOccupancy
**Pattern:** View
**Swim Lane:** Stay

**Trigger:**
- Role: Front Desk Agent
- UI: `[Occupancy Dashboard: room grid with status badges (Available/Occupied), guest name on hover]`
- API: `GET /rooms/occupancy`

**View (green):**
```
RoomOccupancy {
  date: "2026-03-10",
  rooms: [
    { roomId: "r-204", roomNumber: "204", status: "Occupied", guestName: "Alice Dupont", checkOut: "2026-03-12" },
    { roomId: "r-310", roomNumber: "310", status: "Available" }
  ]
}
```
Source events: CheckInCompleted, CheckOutCompleted, RoomAdded

**Specification:**
> Given: CheckInCompleted { roomId: "r-204", guestId: "g-001" }, RoomAdded { roomId: "r-310" }
> Then: r-204 status "Occupied" with guestName "Alice Dupont", r-310 status "Available"

---

### L-1: EarnLoyaltyPoints
**Pattern:** Automation
**Swim Lane:** Guest

**Todo-list view:**
```
CheckOutsWithoutPointsAwarded {
  rows: [{ stayId: "stay-001", guestId: "g-001", nightsStayed: 2, totalPaid: 240.00 }]
}
```
Feeds from: CheckOutCompleted where LoyaltyPointsEarned missing for that stayId

**Robot:** Loyalty Points Awarder (1 point per EUR spent)

**Command (blue):**
```
AwardLoyaltyPoints {
  guestId: "g-001",
  stayId: "stay-001",
  points: 240
}
```

**Event (orange):**
```
LoyaltyPointsEarned {
  guestId: "g-001",
  stayId: "stay-001",
  points: 240,
  newBalance: 240,
  earnedAt: "2026-03-12T11:05:00Z"
}
```

**Specification:**
> Given: Todo view "CheckOutsWithoutPointsAwarded" shows [{ stayId: "stay-001", guestId: "g-001", totalPaid: 240.00 }]
> When: Robot calls AwardLoyaltyPoints { guestId: "g-001", stayId: "stay-001", points: 240 }
> Then: LoyaltyPointsEarned { guestId: "g-001", points: 240, newBalance: 240 } — row removed from todo

---

### L-2: RedeemLoyaltyReward
**Pattern:** Command
**Swim Lane:** Guest

**Trigger:**
- Role: Guest
- UI: `[Rewards Catalog: list of rewards with points cost, balance display — "Redeem" button per reward]`
- API: `POST /loyalty/redeem`

**Command (blue):**
```
RedeemLoyaltyReward {
  guestId: "g-001",
  rewardId: "reward-free-night",
  pointsCost: 200,
  bookingId: "b-9002"
}
```

**Event (orange):**
```
LoyaltyRewardRedeemed {
  guestId: "g-001",
  rewardId: "reward-free-night",
  bookingId: "b-9002",
  pointsDeducted: 200,
  newBalance: 40,
  redeemedAt: "2026-03-15T09:00:00Z"
}
```

**Specification:**
> Given: LoyaltyAccountOpened { guestId: "g-001" }, LoyaltyPointsEarned { guestId: "g-001", points: 240, newBalance: 240 }
> When: RedeemLoyaltyReward { guestId: "g-001", rewardId: "reward-free-night", pointsCost: 200 }
> Then: LoyaltyRewardRedeemed { guestId: "g-001", pointsDeducted: 200, newBalance: 40, redeemedAt: "2026-03-15T09:00:00Z" }

---

## Swim Lane Ownership

| Team | Lane | Slices |
|------|------|--------|
| Identity Team | Guest | G-1 (RegisterGuest), G-2 (GuestProfile), G-3 (OpenLoyaltyAccount) |
| Inventory Team | Inventory | I-1 (AddRoom), I-2 (RoomAvailability) |
| Booking Team | Booking | B-1 (InitiateBooking), B-2 (ConfirmBooking), B-3 (CancelBooking), B-4 (GuestBookings) |
| Payment Team | Payment | P-1 (AuthorizePayment), P-2 (CapturePayment), P-3 (RefundPayment) |
| Stay Team | Stay | S-1 (CheckIn), S-2 (IssueRoomKey), S-3 (CheckOut), S-4 (RoomOccupancy) |
| Loyalty Team | Guest (sub-domain) | L-1 (EarnLoyaltyPoints), L-2 (RedeemLoyaltyReward) |

## Completeness Check

| Criterion | Status | Notes |
|-----------|--------|-------|
| Every UI field traces to an event (origin) or view (destination) | ✅ | All fields traced |
| Every command has a Given-When-Then with realistic data | ✅ | 9 commands with concrete values |
| Every view has a Given-Then specification | ✅ | 4 views with concrete values |
| Every automation has a todo-list view and a produced command | ✅ | 6 automations, each with named todo view |
| No orphan events | ✅ | All 15 events consumed by at least one view or automation |

## Summary

- **Total slices:** 18
- **Patterns:** 8 commands, 4 views, 6 automations, 0 translations
- **Swim lanes:** Guest, Inventory, Booking, Payment, Stay
- **Events:** 15
