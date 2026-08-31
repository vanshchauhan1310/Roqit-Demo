/** Real Hyderabad localities used by the auto trip feed (all inside the
 * service-area bounds — no trip can originate outside Hyderabad). */
export interface HydLocation {
  name: string;
  lat: number;
  lon: number;
}

export const HYD_LOCATIONS: HydLocation[] = [
  { name: "Hitec City", lat: 17.4451, lon: 78.3772 },
  { name: "Gachibowli", lat: 17.4401, lon: 78.3489 },
  { name: "Madhapur", lat: 17.4483, lon: 78.3915 },
  { name: "Banjara Hills", lat: 17.4126, lon: 78.4392 },
  { name: "Jubilee Hills", lat: 17.4239, lon: 78.4098 },
  { name: "Secunderabad", lat: 17.4399, lon: 78.4983 },
  { name: "Ameerpet", lat: 17.4374, lon: 78.4487 },
  { name: "Begumpet", lat: 17.4448, lon: 78.4665 },
  { name: "Kukatpally", lat: 17.4849, lon: 78.4138 },
  { name: "Miyapur", lat: 17.4967, lon: 78.3578 },
  { name: "Kondapur", lat: 17.4615, lon: 78.3639 },
  { name: "Uppal", lat: 17.4009, lon: 78.5583 },
  { name: "LB Nagar", lat: 17.3457, lon: 78.5522 },
  { name: "Charminar", lat: 17.3616, lon: 78.4747 },
  { name: "Malakpet", lat: 17.3725, lon: 78.5199 },
  { name: "Shamshabad", lat: 17.2403, lon: 78.4294 },
  { name: "Kokapet", lat: 17.3866, lon: 78.3337 },
  { name: "Bachupally", lat: 17.5184, lon: 78.3639 },
];

export function randomHydLocation(exclude?: HydLocation): HydLocation {
  let pick = HYD_LOCATIONS[Math.floor(Math.random() * HYD_LOCATIONS.length)];
  if (exclude) {
    while (pick.name === exclude.name) {
      pick = HYD_LOCATIONS[Math.floor(Math.random() * HYD_LOCATIONS.length)];
    }
  }
  return pick;
}