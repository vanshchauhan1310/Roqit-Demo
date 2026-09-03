import { useCallback, useEffect, useRef, useState } from "react";
import { createTrip } from "@/api/trips";
import { randomHydLocation } from "@/utils/hydLocations";

const INTERVAL_MS = 60_000; // one trip every minute
const STORAGE_KEY = "liveops-autofeed";

/**
 * Automated trip feed: posts a new Hyderabad trip every 60s so the Live Ops
 * page behaves like a real streaming ingestion source. Runs entirely client
 * side against the normal POST /api/trips endpoint, so every trip goes
 * through the real queue -> greedy assignment -> LNS pipeline.
 */
export function useTripSimulator() {
  const [enabled, setEnabledState] = useState<boolean>(() => {
    // Default to OFF so LNS runs without competing writers. User can toggle ON.
    return localStorage.getItem(STORAGE_KEY) === "on";
  });
  const [generated, setGenerated] = useState(0);
  const [nextTripInMs, setNextTripInMs] = useState<number>(INTERVAL_MS);
  const [lastTripId, setLastTripId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const nextAtRef = useRef<number>(Date.now() + INTERVAL_MS);
  const generatingRef = useRef(false);

  const setEnabled = useCallback((on: boolean) => {
    setEnabledState(on);
    localStorage.setItem(STORAGE_KEY, on ? "on" : "off");
    nextAtRef.current = Date.now() + INTERVAL_MS;
    setNextTripInMs(INTERVAL_MS);
  }, []);

  const generateNow = useCallback(async () => {
    if (generatingRef.current) return;
    generatingRef.current = true;
    try {
      const origin = randomHydLocation();
      const destination = randomHydLocation(origin);
      const created = await createTrip({
        origin: origin.name,
        destination: destination.name,
        gps_start_lat: origin.lat,
        gps_start_lon: origin.lon,
        gps_end_lat: destination.lat,
        gps_end_lon: destination.lon,
        load_weight_kg: 200 + Math.floor(Math.random() * 1200),
        vehicle_type: "Truck",
      });
      setLastTripId(created.trip_id);
      setGenerated((c) => c + 1);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "failed to generate trip");
    } finally {
      generatingRef.current = false;
      nextAtRef.current = Date.now() + INTERVAL_MS;
    }
  }, []);

  // 1s ticker drives the countdown and fires the generator when due.
  useEffect(() => {
    if (!enabled) return;
    const tick = setInterval(() => {
      const remaining = nextAtRef.current - Date.now();
      if (remaining <= 0) {
        setNextTripInMs(0);
        void generateNow();
      } else {
        setNextTripInMs(remaining);
      }
    }, 1000);
    return () => clearInterval(tick);
  }, [enabled, generateNow]);

  return {
    enabled,
    setEnabled,
    generateNow,
    generated,
    lastTripId,
    nextTripInMs,
    error,
    intervalMs: INTERVAL_MS,
  };
}