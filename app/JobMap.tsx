"use client";
import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// One circle per country, sized by how many jobs in the current view are there.
export type MapPoint = { country: string; lat: number; lng: number; count: number; best: number | null };

export default function JobMap({ points, onPick }: { points: MapPoint[]; onPick: (country: string) => void }) {
  const box = useRef<HTMLDivElement>(null),
    layer = useRef<L.LayerGroup | null>(null),
    pick = useRef(onPick);
  pick.current = onPick;
  useEffect(() => {
    if (!box.current) return;
    const map = L.map(box.current, { worldCopyJump: true, minZoom: 2, scrollWheelZoom: false }).setView([8, 30], 3);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 8,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
      // The app sends no referrer by default; OpenStreetMap's tile servers require one.
      referrerPolicy: "strict-origin-when-cross-origin",
    }).addTo(map);
    layer.current = L.layerGroup().addTo(map);
    return () => {
      map.remove();
      layer.current = null;
    };
  }, []);
  useEffect(() => {
    const group = layer.current;
    if (!group) return;
    group.clearLayers();
    const most = Math.max(1, ...points.map((p) => p.count));
    for (const p of points) {
      const body = document.createElement("div"),
        title = document.createElement("strong"),
        line = document.createElement("p"),
        show = document.createElement("button");
      title.textContent = p.country;
      line.textContent = `${p.count} job${p.count === 1 ? "" : "s"}${p.best != null ? ` · best match ${p.best}` : ""}`;
      show.className = "text-button";
      show.textContent = "Show these jobs";
      show.onclick = () => pick.current(p.country);
      [title, line, show].forEach((el) => body.appendChild(el));
      L.circleMarker([p.lat, p.lng], {
        radius: 7 + 18 * Math.sqrt(p.count / most),
        color: "#1f6f5c",
        weight: 2,
        fillColor: "#2f8f74",
        fillOpacity: 0.5,
      })
        .bindPopup(body)
        .bindTooltip(`${p.country}: ${p.count}`)
        .addTo(group);
    }
  }, [points]);
  return <div ref={box} className="job-map" role="region" aria-label="Map of jobs by country" />;
}
