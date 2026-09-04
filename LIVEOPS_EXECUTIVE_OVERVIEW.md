# Roqit LiveOps Platform — Executive Overview

> **Audience:** Business leaders, operations heads, product owners, and non-technical stakeholders.
> **Companion document:** `LIVEOPS_TECHNICAL_GUIDE.md` (for engineering teams).

---

## 1. What is LiveOps?

**LiveOps** is the *live operations command center* of the Roqit logistics platform. It is the single screen — and the single brain — where a fleet's day actually happens:

- Customer orders (**trips**) arrive continuously.
- The platform **automatically assigns** each order to the best available truck and driver, and builds the delivery route.
- Dispatchers **watch everything in real time** on a live map, with alerts, KPIs, and an activity feed.
- An **AI optimization engine** continuously improves the plan, and **machine-learning models** predict delays, ETAs, fuel burn, and trip cost *before* problems happen.

In one sentence:

> **LiveOps turns fleet dispatching from a manual, reactive phone-call process into an automated, self-optimizing, real-time control loop.**

---

## 2. The Problem It Solves

| Pain point today | How LiveOps fixes it |
|---|---|
| Orders arrive all day; dispatchers assign them manually, one by one | Incoming trips are automatically matched to the best vehicle in seconds |
| Planners can't see the whole fleet at once | A live map shows every vehicle, route, stop, and order status |
| A plan made at 8 AM is obsolete by 10 AM (traffic, cancellations, new orders) | The optimizer continuously re-works the plan; heavy re-optimization can be triggered on demand |
| Delays are discovered *after* the customer complains | ML models flag high delay-risk trips *in advance*, with expected delay in minutes |
| Nobody knows the true cost of a delivery | Fuel consumption and trip cost are predicted per trip from vehicle, road, traffic, and weather data |
| Decisions are unexplainable ("why did the system do that?") | Every optimization decision is **audit-logged**: what changed, before vs. after, cost impact |

---

## 3. What LiveOps Does — The Capabilities

### 3.1 Live Order Intake (the "Incoming Trips" queue)
New customer trips land in an **Incoming Trips** queue on the LiveOps screen. Each trip carries its pickup, drop-off, weight, and time window. The queue updates within seconds of a new order (fast 4-second polling), and trips flow out of the queue automatically as the engine assigns them.

### 3.2 Automatic Trip Assignment (the "Greedy Assigner")
For every incoming trip, the platform:
1. Finds the **candidate vehicles/routes** that could take the trip.
2. Checks **feasibility**: capacity, time windows, driver duty hours.
3. Scores each option with a **cost function** (distance, lateness, utilization, balance).
4. **Inserts the trip** into the best route — pickup stop before delivery stop, in sequence.
5. Publishes the updated plan to the live map and activity feed.

Trips that can't be assigned yet (no feasible vehicle right now) **stay in the queue** and are automatically retried every 60 seconds by a background sweeper — nothing gets lost.

### 3.3 Continuous Plan Improvement (LNS re-optimization)
The initial "insert where it fits" plan is good, not perfect. A **Large Neighborhood Search (LNS)** optimizer periodically *destroys* a slice of the plan (removes ~20% of trips from routes) and *repairs* it in a smarter order (regret-based insertion), keeping the result only if the total cost improves. Operators can trigger this manually with one button (`POST /api/routes/lns/trigger`) — currently the periodic auto-trigger is disabled by design, so humans stay in control of big plan changes.

### 3.4 The Live Map & Plan Views
- Every **active route** drawn on a map (Hyderabad service-area demo data), with color-coded routes.
- Each route shows its **stop sequence** (pickup → delivery), ETAs, and load.
- A **Plan Strip** summarizes today's plan; an **Alert Strip** surfaces what needs attention.
- An **Activity Feed** streams every event: trip created, trip assigned, route optimized, trip completed, delay predicted.

### 3.5 AI/ML Predictions (the ML microservice)
A dedicated ML service answers four questions before dispatch and during execution:
1. **Will this trip be late?** — delay probability per trip (25 features: vehicle, driver history, weather, road type, traffic, route history).
2. **How late?** — expected delay in minutes.
3. **When will it arrive?** — ML ETA prediction (distance, stops, time of day, historical speeds).
4. **What will it cost?** — predicted **fuel liters** and **trip cost in rupees** per trip.

### 3.6 Real-Time Trip Tracking & Simulation
During the day, trips move through their lifecycle (`planned → in-transit → completed`). The platform tracks progress with **GPS breadcrumbs**, updates route stop statuses, detects completions, and — for demos and testing — includes a **trip simulator** that plays out a realistic operating day on demand.

### 3.7 KPIs & Reporting
The LiveOps dashboard tracks, live:
- **Trips today** (total), **assigned vs. unassigned**, **completed**.
- **Active routes** and fleet utilization.
- **Queue depth** (backlog of unassigned trips).
- Fleet, driver, and vehicle rosters; reports endpoints for deeper analysis.

---

## 4. How It Works — The Day in the Life

```
 Customer order placed
        │
        ▼
 [Incoming Trips queue] ──(seconds)──► Greedy Assignment Engine
        │                                     │  feasibility check
        │                                     │  cost scoring
        │                                     ▼
        │                        Trip inserted into best route
        │                        (unassigned trips retried every 60 s)
        │                                     │
        ▼                                     ▼
 Live Map / Plan Strip / Alerts / Activity Feed  ◄── real-time updates
        │
        ▼
 (On demand) LNS Re-optimizer: destroy 20% of plan → re-insert smarter
        │         only accepted if cost improves; full audit trail
        ▼
 Trips executed: GPS breadcrumbs, stop statuses, ML delay/ETA watch
        │
        ▼
 Trip completed → route finished, KPIs updated, reports
```

**Human-in-the-loop by design:** the system automates the repetitive work (assignment, retries, tracking) but keeps the big levers (triggering a full re-optimization) in the dispatcher's hands.

---

## 5. Why It Matters — Business Value

- **Speed:** order-to-assignment in seconds, not minutes; dispatchers manage exceptions instead of the whole board.
- **Lower cost per delivery:** cost-function-driven assignment plus LNS re-optimization measurably reduce distance, lateness, and fuel burn.
- **Fewer missed SLAs:** ML delay-risk flags let teams act *before* a customer notices.
- **Full transparency:** live map, activity feed, and per-decision audit logs — no black box.
- **Scales with the fleet:** the engine works the same for 5 trucks or 500; workers run in the background and the UI stays responsive.
- **Demo-ready:** the built-in trip simulator can demonstrate an entire operating day to stakeholders or for testing, without a real fleet.

---

## 6. Who Uses What

| Role | What they use LiveOps for |
|---|---|
| **Dispatcher / Ops controller** | Watch the live map & queue, monitor alerts, trigger re-optimization, spot stuck trips |
| **Fleet manager** | KPIs (trips, utilization, backlog), fleet & driver rosters, reports |
| **Customer service** | Live trip status, predicted ETAs, delay-risk flags |
| **Executive / leadership** | Dashboards for throughput, cost, and service level; audit trails for accountability |
| **Engineering / QA** | Trip simulator, audit logs, health endpoints, real-time event stream |

---

## 7. Glossary (plain-English)

| Term | Meaning |
|---|---|
| **Trip** | One customer order: pick up goods at A, deliver at B, with weight and time window |
| **Route** | A vehicle's stop-by-stop plan for the day (sequence of pickups/deliveries) |
| **Assignment** | Deciding which vehicle/route will execute a trip |
| **Greedy insertion** | Fast method: put each new trip in the cheapest feasible spot right away |
| **LNS (Large Neighborhood Search)** | Smarter method: tear out part of the plan and rebuild it better; keep only if improved |
| **Regret insertion** | Re-insert trips in order of "how much it hurts to leave this one out" |
| **Delay risk** | ML probability (0–100%) that a trip will arrive late |
| **ETA** | Estimated time of arrival, predicted by an ML model |
| **KPI** | Key performance indicator (trips today, backlog, completion rate, etc.) |
| **Breadcrumbs** | GPS position points recorded as a vehicle moves |

---

*For architecture diagrams, data models, algorithms, API reference, and deployment details, see `LIVEOPS_TECHNICAL_GUIDE.md`.*



