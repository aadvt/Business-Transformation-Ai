"use client";

import { useEffect, useMemo, useRef } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import * as THREE from "three";
import { useDisruptions, useVendors } from "@/lib/queries";
import { isFailedStage, isTerminalStage } from "@/lib/types";
import type { DisruptionStage, DisruptionSummary, Vendor } from "@/lib/types";

const MAPBOX_TOKEN = process.env.NEXT_PUBLIC_MAPBOX_TOKEN ?? "";

// Not a vendor — the manufacturer's own plant, referenced in disruption
// headlines ("line stoppage risk at Chakan plant"). Fixed, not fixture data.
const CHAKAN_PLANT = { name: "Chakan Plant", lat: 18.7578, lng: 73.8637 };

const MAP_CENTER: [number, number] = [78.5, 21.5];
const MAP_ZOOM = 4.3;

type SeverityTier = "critical" | "elevated" | "moderate";

const SEVERITY_COLOR: Record<SeverityTier, number> = {
  critical: 0xd8484d,
  elevated: 0xcf9a37,
  moderate: 0x4d80b8,
};

const SEVERITY_HEX: Record<SeverityTier, string> = {
  critical: "#d8484d",
  elevated: "#cf9a37",
  moderate: "#4d80b8",
};

// Higher severity = faster flow along the arc.
const SEVERITY_SPEED: Record<SeverityTier, number> = {
  critical: 0.00042,
  elevated: 0.0003,
  moderate: 0.00022,
};

const PLANT_COLOR = 0xcf9a37;
const OUTLINE_COLOR = 0xffffff;

// Mercator units — the whole world is 1.0 wide, so these are deliberately
// tiny. Markers are flat discs sized to read as city dots.
const NODE_RADIUS = 0.0002;
const NODE_OUTLINE_SCALE = 1.45;
const PLANT_RADIUS = 0.00032;
const PARTICLE_RADIUS = 0.00009;
const EDGE_TUBE_RADIUS = 0.00005;
const PULSE_RING_INNER = 0.00034;
const PULSE_RING_OUTER = 0.00042;

const ARC_PEAK_ALTITUDE_M = 190000;
const PARTICLES_PER_EDGE = 4;
const PULSE_RING_PERIOD_MS = 2600;

function isLiveStage(stage: DisruptionStage): boolean {
  return !isTerminalStage(stage) && !isFailedStage(stage);
}

function severityForExposurePaise(paise: number): SeverityTier {
  const rupees = paise / 100;
  if (rupees >= 1_00_00_000) return "critical";
  if (rupees >= 25_00_000) return "elevated";
  return "moderate";
}

function hslToHex(h: number, s: number, l: number): number {
  const sNorm = s / 100;
  const lNorm = l / 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = sNorm * Math.min(lNorm, 1 - lNorm);
  const f = (n: number) => lNorm - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return (Math.round(f(0) * 255) << 16) | (Math.round(f(8) * 255) << 8) | Math.round(f(4) * 255);
}

function reliabilityColor(score: number): number {
  const hue = Math.max(0, Math.min(100, score)) * 1.2; // 0 (red) -> 120 (green)
  return hslToHex(hue, 55, 52);
}

function mercator(lng: number, lat: number, altitude = 0) {
  return mapboxgl.MercatorCoordinate.fromLngLat({ lng, lat }, altitude);
}

/** Flat, unlit fill. Everything in this scene is a solid colour on purpose —
 *  shaded 3D volumes read as heavy blobs the moment the camera moves, where
 *  flat markers stay legible at any pitch or bearing. */
function flatMaterial(color: number, opacity = 1): THREE.MeshBasicMaterial {
  return new THREE.MeshBasicMaterial({
    color,
    transparent: opacity < 1,
    opacity,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
}

function disposeObject3D(root: THREE.Object3D) {
  root.traverse((child) => {
    const withGeometry = child as unknown as { geometry?: THREE.BufferGeometry };
    withGeometry.geometry?.dispose();
    const withMaterial = child as unknown as { material?: THREE.Material | THREE.Material[] };
    const material = withMaterial.material;
    if (Array.isArray(material)) material.forEach((m) => m.dispose());
    else material?.dispose();
  });
}

interface EdgeAnim {
  curve: THREE.QuadraticBezierCurve3;
  particles: THREE.Object3D[];
  offsets: number[];
  speed: number;
}

interface PulseRing {
  mesh: THREE.Mesh;
  material: THREE.MeshBasicMaterial;
  phase: number;
  maxScale: number;
}

export default function NetworkMap() {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<mapboxgl.Map | null>(null);
  const rebuildSceneRef = useRef<(() => void) | null>(null);
  const vendorsRef = useRef<Vendor[]>([]);
  const disruptionsRef = useRef<DisruptionSummary[]>([]);

  const { data: vendorsData } = useVendors();
  const { data: disruptionsData } = useDisruptions();

  const vendors = useMemo(() => vendorsData?.items ?? [], [vendorsData]);
  const disruptions = useMemo(() => disruptionsData?.items ?? [], [disruptionsData]);

  const liveCount = useMemo(() => disruptions.filter((d) => isLiveStage(d.stage)).length, [disruptions]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current || !MAPBOX_TOKEN) return;

    mapboxgl.accessToken = MAPBOX_TOKEN;
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/light-v11",
      center: MAP_CENTER,
      zoom: MAP_ZOOM,
      pitch: 40,
      bearing: 0,
      antialias: true,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), "top-right");

    const popup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, offset: 14 });
    popup.addClassName("sanjeevani-popup");

    const scene = new THREE.Scene();
    const camera = new THREE.Camera();
    let renderer: THREE.WebGLRenderer | null = null;

    const contentGroup = new THREE.Group();
    scene.add(contentGroup);

    const edges: EdgeAnim[] = [];
    const pulseRings: PulseRing[] = [];
    // Markers are flat discs turned to face the camera every frame, so they
    // stay perfect circles instead of foreshortening into slivers on tilt.
    const billboards: THREE.Object3D[] = [];
    let rafId: number | null = null;
    const cameraPos = new THREE.Vector3();

    const customLayer: mapboxgl.CustomLayerInterface = {
      id: "sanjeevani-network",
      type: "custom",
      renderingMode: "3d",
      onAdd(_map, gl) {
        renderer = new THREE.WebGLRenderer({ canvas: map.getCanvas(), context: gl, antialias: true });
        renderer.autoClear = false;
      },
      render(_gl, matrixArray) {
        if (!renderer) return;

        const free = map.getFreeCameraOptions();
        if (free.position) {
          cameraPos.set(free.position.x, free.position.y, free.position.z);
          for (const b of billboards) b.lookAt(cameraPos);
        }

        camera.projectionMatrix = new THREE.Matrix4().fromArray(matrixArray);
        renderer.resetState();
        renderer.render(scene, camera);
      },
    };

    /** A solid disc with a dark outline ring behind it — the outline is what
     *  keeps the marker readable over both light coastlines and dark ocean. */
    function addMarker(at: THREE.Vector3, radius: number, color: number, renderOrder: number) {
      const group = new THREE.Group();
      group.position.copy(at);

      const outline = new THREE.Mesh(
        new THREE.CircleGeometry(radius * NODE_OUTLINE_SCALE, 32),
        flatMaterial(OUTLINE_COLOR, 0.85)
      );
      outline.renderOrder = renderOrder;
      group.add(outline);

      const fill = new THREE.Mesh(new THREE.CircleGeometry(radius, 32), flatMaterial(color));
      fill.position.z = 0.0000002; // hairline lift so the fill always wins the depth test
      fill.renderOrder = renderOrder + 1;
      group.add(fill);

      contentGroup.add(group);
      billboards.push(group);
    }

    function addGroundPulse(at: THREE.Vector3, color: number, phase: number, maxScale: number) {
      const material = flatMaterial(color, 0);
      const mesh = new THREE.Mesh(new THREE.RingGeometry(PULSE_RING_INNER, PULSE_RING_OUTER, 48), material);
      mesh.position.copy(at);
      contentGroup.add(mesh);
      pulseRings.push({ mesh, material, phase, maxScale });
    }

    function buildPlant() {
      const pos = mercator(CHAKAN_PLANT.lng, CHAKAN_PLANT.lat);
      const at = new THREE.Vector3(pos.x, pos.y, pos.z);

      // Square marker rotated 45°, so the hub is distinguishable from the
      // round vendor dots by silhouette alone rather than only by colour.
      const group = new THREE.Group();
      group.position.copy(at);

      const outline = new THREE.Mesh(
        new THREE.PlaneGeometry(PLANT_RADIUS * 2.5, PLANT_RADIUS * 2.5),
        flatMaterial(OUTLINE_COLOR, 0.85)
      );
      outline.rotation.z = Math.PI / 4;
      outline.renderOrder = 10;
      group.add(outline);

      const fill = new THREE.Mesh(
        new THREE.PlaneGeometry(PLANT_RADIUS * 1.8, PLANT_RADIUS * 1.8),
        flatMaterial(PLANT_COLOR)
      );
      fill.rotation.z = Math.PI / 4;
      fill.position.z = 0.0000002;
      fill.renderOrder = 11;
      group.add(fill);

      contentGroup.add(group);
      billboards.push(group);

      for (let i = 0; i < 2; i++) addGroundPulse(at, PLANT_COLOR, i / 2, 6);

      return at;
    }

    function buildVendor(vendor: Vendor, plantAt: THREE.Vector3) {
      const pos = mercator(vendor.lng, vendor.lat);
      const at = new THREE.Vector3(pos.x, pos.y, pos.z);

      const disruption = disruptionsRef.current.find((d) => d.vendor.id === vendor.id && isLiveStage(d.stage));
      const severity = disruption ? severityForExposurePaise(disruption.exposure_total_paise) : null;

      // Undisrupted vendors are coloured by reliability; a live disruption
      // overrides that with its severity colour, since that is the thing an
      // operator needs to spot first.
      const color = severity ? SEVERITY_COLOR[severity] : reliabilityColor(vendor.reliability_score_0_100);

      addMarker(at, NODE_RADIUS, color, 20);

      if (!disruption || !severity) return;

      addGroundPulse(at, SEVERITY_COLOR[severity], Math.random(), 4);
      buildEdge(plantAt, at, vendor, SEVERITY_COLOR[severity], severity);
    }

    function buildEdge(
      from: THREE.Vector3,
      to: THREE.Vector3,
      vendor: Vendor,
      color: number,
      severity: SeverityTier
    ) {
      // Arc height scales with ground distance so short hops don't balloon.
      const span = from.distanceTo(to);
      const peak = ARC_PEAK_ALTITUDE_M * (0.5 + Math.min(span / 0.05, 1.6));
      const midPos = mercator((CHAKAN_PLANT.lng + vendor.lng) / 2, (CHAKAN_PLANT.lat + vendor.lat) / 2, peak);
      const mid = new THREE.Vector3(midPos.x, midPos.y, midPos.z);
      const curve = new THREE.QuadraticBezierCurve3(from, mid, to);

      const tube = new THREE.Mesh(
        new THREE.TubeGeometry(curve, 72, EDGE_TUBE_RADIUS, 6, false),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.55, depthWrite: false })
      );
      contentGroup.add(tube);

      const particles: THREE.Object3D[] = [];
      const offsets: number[] = [];
      for (let i = 0; i < PARTICLES_PER_EDGE; i++) {
        const dot = new THREE.Mesh(new THREE.CircleGeometry(PARTICLE_RADIUS, 16), flatMaterial(0xffffff));
        dot.renderOrder = 30;
        contentGroup.add(dot);
        billboards.push(dot);
        particles.push(dot);
        offsets.push(i / PARTICLES_PER_EDGE);
      }

      edges.push({ curve, particles, offsets, speed: SEVERITY_SPEED[severity] });
    }

    function rebuildScene() {
      while (contentGroup.children.length > 0) {
        const child = contentGroup.children[0];
        disposeObject3D(child);
        contentGroup.remove(child);
      }
      edges.length = 0;
      pulseRings.length = 0;
      billboards.length = 0;

      const plantAt = buildPlant();
      for (const vendor of vendorsRef.current) buildVendor(vendor, plantAt);

      map.triggerRepaint();
    }
    rebuildSceneRef.current = rebuildScene;

    function startAnimation() {
      let last = performance.now();
      let elapsed = 0;

      function tick(now: number) {
        const dt = Math.min(now - last, 64);
        last = now;
        elapsed += dt;

        for (const edge of edges) {
          edge.particles.forEach((particle, i) => {
            edge.offsets[i] = (edge.offsets[i] + edge.speed * dt) % 1;
            particle.position.copy(edge.curve.getPointAt(edge.offsets[i]));
          });
        }

        for (const ring of pulseRings) {
          const t = (((elapsed / PULSE_RING_PERIOD_MS + ring.phase) % 1) + 1) % 1;
          const scale = 1 + t * (ring.maxScale - 1);
          ring.mesh.scale.set(scale, scale, scale);
          ring.material.opacity = 0.38 * (1 - t) * (1 - t);
        }

        map.triggerRepaint();
        rafId = requestAnimationFrame(tick);
      }
      rafId = requestAnimationFrame(tick);
    }

    function handleMouseMove(e: mapboxgl.MapMouseEvent) {
      let closest: { vendor: Vendor; dist: number } | null = null;
      for (const vendor of vendorsRef.current) {
        const point = map.project([vendor.lng, vendor.lat]);
        const dist = Math.hypot(point.x - e.point.x, point.y - e.point.y);
        // Screen-space, so it stays a comfortable target even though the
        // markers are deliberately small.
        if (dist < 15 && (!closest || dist < closest.dist)) closest = { vendor, dist };
      }

      if (!closest) {
        popup.remove();
        map.getCanvas().style.cursor = "";
        return;
      }
      map.getCanvas().style.cursor = "pointer";

      const vendor = closest.vendor;
      const disruption = disruptionsRef.current.find((d) => d.vendor.id === vendor.id && isLiveStage(d.stage));
      const severity = disruption ? severityForExposurePaise(disruption.exposure_total_paise) : null;

      const html = `
        <div style="min-width:200px">
          <div style="font-weight:600;font-size:12px;margin-bottom:2px;">${vendor.name}</div>
          <div style="font-size:11px;opacity:0.6;margin-bottom:8px;">${vendor.city}, ${vendor.state}</div>
          <div style="display:flex;gap:12px;font-size:11px;">
            <div><div style="opacity:0.55;">Reliability</div><div style="font-weight:600;">${vendor.reliability_score_0_100}%</div></div>
            <div><div style="opacity:0.55;">On-time</div><div style="font-weight:600;">${Math.round(vendor.on_time_rate * 100)}%</div></div>
            <div><div style="opacity:0.55;">Dues</div><div style="font-weight:600;">${vendor.dues_display}</div></div>
          </div>
          ${
            disruption && severity
              ? `<div style="border-top:1px solid rgba(255,255,255,0.09);margin-top:8px;padding-top:7px;">
                   <div style="display:inline-block;font-size:9px;font-weight:700;letter-spacing:0.07em;text-transform:uppercase;color:${SEVERITY_HEX[severity]};margin-bottom:4px;">${severity}</div>
                   <div style="font-size:11px;line-height:1.45;">${disruption.headline}</div>
                   <div style="font-size:11px;font-weight:600;margin-top:4px;color:${SEVERITY_HEX[severity]};">${disruption.exposure_total_display} exposure</div>
                 </div>`
              : ``
          }
        </div>
      `;
      popup.setLngLat([vendor.lng, vendor.lat]).setHTML(html).addTo(map);
    }

    map.on("load", () => {
      map.addLayer(customLayer);
      rebuildScene();
      startAnimation();
    });
    map.on("mousemove", handleMouseMove);
    map.on("mouseout", () => popup.remove());

    return () => {
      if (rafId) cancelAnimationFrame(rafId);
      popup.remove();
      disposeObject3D(scene);
      renderer?.dispose();
      map.remove();
      mapRef.current = null;
      rebuildSceneRef.current = null;
    };
  }, []);

  useEffect(() => {
    vendorsRef.current = vendors;
    disruptionsRef.current = disruptions;
    rebuildSceneRef.current?.();
  }, [vendors, disruptions]);

  if (!MAPBOX_TOKEN) {
    return (
      <div className="panel flex h-full items-center justify-center text-[13px] text-ink-faint">
        NEXT_PUBLIC_MAPBOX_TOKEN is not set.
      </div>
    );
  }

  return (
    <div className="panel-flush relative h-full">
      <div ref={containerRef} className="h-full w-full" />

      <div className="pointer-events-none absolute top-3 left-3 rounded-md border border-line bg-surface/95 px-3 py-2">
        <span className="eyebrow">Supply network</span>
        <p className="numeric mt-1 text-[20px] leading-none font-medium text-ink" data-numeric>
          {vendors.length}
        </p>
        <p className="mt-1 text-[11px] text-ink-muted">
          vendors · <span className="text-accent">{liveCount} live</span>
        </p>
      </div>

      <div className="pointer-events-none absolute bottom-3 left-3 rounded-md border border-line bg-surface/95 px-3 py-2.5">
        <span className="eyebrow">Severity</span>
        <div className="mt-1.5 space-y-1">
          {(["critical", "elevated", "moderate"] as SeverityTier[]).map((tier) => (
            <div key={tier} className="flex items-center gap-2 text-[11px] text-ink-muted">
              <span className="h-1.5 w-1.5 rounded-full" style={{ background: SEVERITY_HEX[tier] }} />
              <span className="w-14 capitalize">{tier}</span>
              <span className="numeric text-ink-faint">
                {tier === "critical" ? "≥ ₹1Cr" : tier === "elevated" ? "≥ ₹25L" : "< ₹25L"}
              </span>
            </div>
          ))}
        </div>
        <div className="mt-2 space-y-1 border-t border-line pt-2">
          <div className="flex items-center gap-2 text-[11px] text-ink-muted">
            <span className="h-1.5 w-1.5 rotate-45" style={{ background: "#cf9a37" }} />
            Chakan plant
          </div>
          <div className="flex items-center gap-2 text-[11px] text-ink-muted">
            <span className="h-1.5 w-1.5 rounded-full bg-success" />
            Vendor · reliability
          </div>
        </div>
      </div>
    </div>
  );
}
