"use client";

import { useEffect, useMemo, useRef } from "react";
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import * as THREE from "three";
import { motion } from "framer-motion";
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
  critical: 0xff5d70,
  elevated: 0xe8a33d,
  moderate: 0x62b6f5,
};

const SEVERITY_HEX: Record<SeverityTier, string> = {
  critical: "#ff5d70",
  elevated: "#e8a33d",
  moderate: "#62b6f5",
};

// Higher severity = faster flow + more urgent pulse.
const SEVERITY_SPEED: Record<SeverityTier, number> = {
  critical: 0.00042,
  elevated: 0.0003,
  moderate: 0.00022,
};

const PLANT_COLOR = 0xf7c163;

// All sizes are in Mercator units (the whole world is 1.0 wide), so these
// are deliberately tiny — see mercator() below. Scaled so a vendor core
// reads as a city dot on the map rather than a landmass; the halo/glow
// shells and beams are scaled with it so the proportions hold.
const NODE_CORE_RADIUS = 0.00018;
const NODE_GLOW_RADIUS = 0.00048;
const NODE_HALO_INNER = 0.00037;
const NODE_HALO_OUTER = 0.00063;
const PLANT_CORE_RADIUS = 0.0003;
const PLANT_RING_RADIUS = 0.00063;
const PLANT_GLOW_RADIUS = 0.00087;
const PARTICLE_CORE_RADIUS = 0.00008;
const PARTICLE_HALO_RADIUS = 0.00021;
// Edges shrink less than the nodes — at 1/3 the arcs stop reading as flow.
const EDGE_TUBE_RADIUS = 0.000055;
const BEAM_RADIUS = 0.000055;

const ARC_PEAK_ALTITUDE_M = 190000;
const BEAM_HEIGHT = 0.0017;
const PLANT_BEAM_HEIGHT = 0.0031;
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
  return hslToHex(hue, 65, 55);
}

function mercator(lng: number, lat: number, altitude = 0) {
  return mapboxgl.MercatorCoordinate.fromLngLat({ lng, lat }, altitude);
}

/** Rim-light (fresnel) shader — brightest where the surface turns away from
 *  the camera, which is what reads as a soft volumetric halo rather than a
 *  flat translucent ball. Needs the real camera position, which Mapbox
 *  exposes via getFreeCameraOptions().position (updated per frame in
 *  render()) — three.js's own camera matrices are bypassed here because the
 *  projection matrix is handed to us wholesale by Mapbox. */
const GLOW_VERTEX = /* glsl */ `
  varying vec3 vNormalW;
  varying vec3 vWorldPos;
  void main() {
    vNormalW = normalize(normalMatrix * normal);
    vWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

const GLOW_FRAGMENT = /* glsl */ `
  uniform vec3 uColor;
  uniform vec3 uCameraPos;
  uniform float uIntensity;
  uniform float uPower;
  varying vec3 vNormalW;
  varying vec3 vWorldPos;
  void main() {
    vec3 viewDir = normalize(uCameraPos - vWorldPos);
    float fres = pow(1.0 - abs(dot(viewDir, normalize(vNormalW))), uPower);
    gl_FragColor = vec4(uColor, clamp(fres * uIntensity, 0.0, 1.0));
  }
`;

function createGlowMaterial(color: number, intensity: number, power: number): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    uniforms: {
      uColor: { value: new THREE.Color(color) },
      uCameraPos: { value: new THREE.Vector3() },
      uIntensity: { value: intensity },
      uPower: { value: power },
    },
    vertexShader: GLOW_VERTEX,
    fragmentShader: GLOW_FRAGMENT,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    side: THREE.BackSide,
  });
}

/** Vertical light column so a node still reads at a shallow camera pitch,
 *  fading out with height. UV.y runs 0 (base) -> 1 (top) on a cylinder. */
const BEAM_FRAGMENT = /* glsl */ `
  uniform vec3 uColor;
  uniform float uIntensity;
  varying vec2 vUvB;
  void main() {
    float a = pow(1.0 - vUvB.y, 2.2) * uIntensity;
    gl_FragColor = vec4(uColor, a);
  }
`;

const BEAM_VERTEX = /* glsl */ `
  varying vec2 vUvB;
  void main() {
    vUvB = uv;
    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
  }
`;

function createBeamMaterial(color: number, intensity: number): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    uniforms: {
      uColor: { value: new THREE.Color(color) },
      uIntensity: { value: intensity },
    },
    vertexShader: BEAM_VERTEX,
    fragmentShader: BEAM_FRAGMENT,
    transparent: true,
    blending: THREE.AdditiveBlending,
    depthWrite: false,
    side: THREE.DoubleSide,
  });
}

/** Cylinder geometry is Y-up and origin-centred; Mercator's up axis is +Z,
 *  so translate the base to the origin, then swing Y onto Z. */
function makeBeamGeometry(radius: number, height: number): THREE.CylinderGeometry {
  const geom = new THREE.CylinderGeometry(radius * 0.35, radius, height, 12, 1, true);
  geom.translate(0, height / 2, 0);
  geom.rotateX(Math.PI / 2);
  return geom;
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

interface NodeAnim {
  glowMaterial: THREE.ShaderMaterial;
  baseIntensity: number;
  phase: number;
  live: boolean;
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

  const liveCount = useMemo(
    () => disruptions.filter((d) => isLiveStage(d.stage)).length,
    [disruptions]
  );

  useEffect(() => {
    if (!containerRef.current || mapRef.current || !MAPBOX_TOKEN) return;

    mapboxgl.accessToken = MAPBOX_TOKEN;
    const map = new mapboxgl.Map({
      container: containerRef.current,
      style: "mapbox://styles/mapbox/dark-v11",
      center: MAP_CENTER,
      zoom: MAP_ZOOM,
      pitch: 52,
      bearing: -12,
      antialias: true,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new mapboxgl.NavigationControl({ visualizePitch: true }), "top-right");

    const popup = new mapboxgl.Popup({ closeButton: false, closeOnClick: false, offset: 18 });
    popup.addClassName("sanjeevani-popup");

    const scene = new THREE.Scene();
    const camera = new THREE.Camera();
    let renderer: THREE.WebGLRenderer | null = null;

    // Lights are added once and never cleared; only contentGroup is rebuilt
    // when the underlying vendor/disruption data changes.
    const lightRig = new THREE.Group();
    lightRig.add(new THREE.AmbientLight(0xffffff, 1.15));
    const keyLight = new THREE.DirectionalLight(0xfff0d8, 2.1);
    keyLight.position.set(0.6, 0.2, 1);
    lightRig.add(keyLight);
    const rimLight = new THREE.DirectionalLight(0x6fa8ff, 1.3);
    rimLight.position.set(-0.7, -0.5, 0.4);
    lightRig.add(rimLight);
    scene.add(lightRig);

    const contentGroup = new THREE.Group();
    scene.add(contentGroup);

    const edges: EdgeAnim[] = [];
    const pulseRings: PulseRing[] = [];
    const nodeAnims: NodeAnim[] = [];
    const glowMaterials: THREE.ShaderMaterial[] = [];
    let plantRing: THREE.Mesh | null = null;
    let plantCore: THREE.Mesh | null = null;
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

        // Feed the real camera position to every fresnel material — without
        // it the rim light is computed against the Mercator origin and the
        // glow sits on the wrong side of each object.
        const free = map.getFreeCameraOptions();
        if (free.position) {
          cameraPos.set(free.position.x, free.position.y, free.position.z);
          for (const mat of glowMaterials) mat.uniforms.uCameraPos.value.copy(cameraPos);
        }

        camera.projectionMatrix = new THREE.Matrix4().fromArray(matrixArray);
        renderer.resetState();
        renderer.render(scene, camera);
      },
    };

    function addGlow(mesh: THREE.Mesh, material: THREE.ShaderMaterial) {
      glowMaterials.push(material);
      contentGroup.add(mesh);
    }

    function buildPlant() {
      const pos = mercator(CHAKAN_PLANT.lng, CHAKAN_PLANT.lat);
      const at = new THREE.Vector3(pos.x, pos.y, pos.z);

      const core = new THREE.Mesh(
        new THREE.IcosahedronGeometry(PLANT_CORE_RADIUS, 1),
        new THREE.MeshStandardMaterial({
          color: PLANT_COLOR,
          emissive: new THREE.Color(PLANT_COLOR),
          emissiveIntensity: 0.85,
          roughness: 0.28,
          metalness: 0.65,
          flatShading: true,
        })
      );
      core.position.copy(at);
      contentGroup.add(core);
      plantCore = core;

      // Orbiting torus — the only rotating element, so the hub reads as
      // "active" even when no disruption edges are live.
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(PLANT_RING_RADIUS, PLANT_RING_RADIUS * 0.055, 10, 64),
        new THREE.MeshBasicMaterial({ color: PLANT_COLOR, transparent: true, opacity: 0.55 })
      );
      ring.position.copy(at);
      contentGroup.add(ring);
      plantRing = ring;

      const glowMat = createGlowMaterial(PLANT_COLOR, 1.15, 2.4);
      const glow = new THREE.Mesh(new THREE.SphereGeometry(PLANT_GLOW_RADIUS, 24, 24), glowMat);
      glow.position.copy(at);
      addGlow(glow, glowMat);

      const beam = new THREE.Mesh(
        makeBeamGeometry(BEAM_RADIUS * 1.5, PLANT_BEAM_HEIGHT),
        createBeamMaterial(PLANT_COLOR, 0.5)
      );
      beam.position.copy(at);
      contentGroup.add(beam);

      const halo = new THREE.Mesh(
        new THREE.RingGeometry(PLANT_RING_RADIUS * 1.1, PLANT_RING_RADIUS * 1.5, 64),
        new THREE.MeshBasicMaterial({
          color: PLANT_COLOR,
          transparent: true,
          opacity: 0.2,
          side: THREE.DoubleSide,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        })
      );
      halo.position.copy(at);
      contentGroup.add(halo);

      // Two rings out of phase so the hub emits a continuous "radar" sweep.
      for (let i = 0; i < 2; i++) {
        const ringMat = new THREE.MeshBasicMaterial({
          color: PLANT_COLOR,
          transparent: true,
          opacity: 0,
          side: THREE.DoubleSide,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        });
        const pulse = new THREE.Mesh(
          new THREE.RingGeometry(PLANT_RING_RADIUS * 0.9, PLANT_RING_RADIUS * 1.02, 64),
          ringMat
        );
        pulse.position.copy(at);
        contentGroup.add(pulse);
        pulseRings.push({ mesh: pulse, material: ringMat, phase: i / 2, maxScale: 5.5 });
      }

      return at;
    }

    function buildVendor(vendor: Vendor, plantAt: THREE.Vector3) {
      const pos = mercator(vendor.lng, vendor.lat);
      const at = new THREE.Vector3(pos.x, pos.y, pos.z);
      const nodeColor = reliabilityColor(vendor.reliability_score_0_100);

      const disruption = disruptionsRef.current.find((d) => d.vendor.id === vendor.id && isLiveStage(d.stage));
      const severity = disruption ? severityForExposurePaise(disruption.exposure_total_paise) : null;
      const accentColor = severity ? SEVERITY_COLOR[severity] : nodeColor;

      // Dues nudge the core size so a heavier payable reads as a bigger node.
      const duesFactor = Math.min(vendor.dues_paise / 1_000_000_00, 1);
      const coreRadius = NODE_CORE_RADIUS * (0.85 + duesFactor * 0.5);

      const core = new THREE.Mesh(
        new THREE.SphereGeometry(coreRadius, 28, 28),
        new THREE.MeshStandardMaterial({
          color: nodeColor,
          emissive: new THREE.Color(nodeColor),
          emissiveIntensity: 0.55,
          roughness: 0.25,
          metalness: 0.5,
        })
      );
      core.position.copy(at);
      contentGroup.add(core);

      const glowMat = createGlowMaterial(accentColor, disruption ? 1.25 : 0.7, 2.8);
      const glow = new THREE.Mesh(new THREE.SphereGeometry(NODE_GLOW_RADIUS, 22, 22), glowMat);
      glow.position.copy(at);
      addGlow(glow, glowMat);
      nodeAnims.push({
        glowMaterial: glowMat,
        baseIntensity: disruption ? 1.25 : 0.7,
        phase: Math.random(),
        live: Boolean(disruption),
      });

      const halo = new THREE.Mesh(
        new THREE.RingGeometry(NODE_HALO_INNER, NODE_HALO_OUTER, 48),
        new THREE.MeshBasicMaterial({
          color: accentColor,
          transparent: true,
          opacity: disruption ? 0.35 : 0.16,
          side: THREE.DoubleSide,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        })
      );
      halo.position.copy(at);
      contentGroup.add(halo);

      const beam = new THREE.Mesh(
        makeBeamGeometry(BEAM_RADIUS, BEAM_HEIGHT),
        createBeamMaterial(accentColor, disruption ? 0.45 : 0.22)
      );
      beam.position.copy(at);
      contentGroup.add(beam);

      if (!disruption || !severity) return;

      // Expanding ground ring, one per disrupted vendor.
      const ringMat = new THREE.MeshBasicMaterial({
        color: accentColor,
        transparent: true,
        opacity: 0,
        side: THREE.DoubleSide,
        blending: THREE.AdditiveBlending,
        depthWrite: false,
      });
      const pulse = new THREE.Mesh(new THREE.RingGeometry(NODE_HALO_INNER, NODE_HALO_INNER * 1.16, 48), ringMat);
      pulse.position.copy(at);
      contentGroup.add(pulse);
      pulseRings.push({ mesh: pulse, material: ringMat, phase: Math.random(), maxScale: 4 });

      buildEdge(plantAt, at, vendor, accentColor, severity);
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
        new THREE.TubeGeometry(curve, 72, EDGE_TUBE_RADIUS, 8, false),
        new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.5 })
      );
      contentGroup.add(tube);

      const sheathMat = createGlowMaterial(color, 0.75, 2.0);
      const sheath = new THREE.Mesh(
        new THREE.TubeGeometry(curve, 72, EDGE_TUBE_RADIUS * 3.4, 8, false),
        sheathMat
      );
      addGlow(sheath, sheathMat);

      const particles: THREE.Object3D[] = [];
      const offsets: number[] = [];
      for (let i = 0; i < PARTICLES_PER_EDGE; i++) {
        const comet = new THREE.Group();
        comet.add(
          new THREE.Mesh(
            new THREE.SphereGeometry(PARTICLE_CORE_RADIUS, 10, 10),
            new THREE.MeshBasicMaterial({ color: 0xffffff })
          )
        );
        const haloMat = new THREE.MeshBasicMaterial({
          color,
          transparent: true,
          opacity: 0.55,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
        });
        comet.add(new THREE.Mesh(new THREE.SphereGeometry(PARTICLE_HALO_RADIUS, 12, 12), haloMat));
        contentGroup.add(comet);
        particles.push(comet);
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
      nodeAnims.length = 0;
      glowMaterials.length = 0;
      plantRing = null;
      plantCore = null;

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
          const t = ((elapsed / PULSE_RING_PERIOD_MS + ring.phase) % 1 + 1) % 1;
          const scale = 1 + t * (ring.maxScale - 1);
          ring.mesh.scale.set(scale, scale, scale);
          ring.material.opacity = 0.42 * (1 - t) * (1 - t);
        }

        for (const node of nodeAnims) {
          const speed = node.live ? 0.0026 : 0.0012;
          const swing = node.live ? 0.4 : 0.18;
          const wave = Math.sin(elapsed * speed + node.phase * Math.PI * 2);
          node.glowMaterial.uniforms.uIntensity.value = node.baseIntensity * (1 + wave * swing);
        }

        if (plantRing) {
          plantRing.rotation.z += dt * 0.0009;
          plantRing.rotation.x = Math.PI * 0.28 + Math.sin(elapsed * 0.0005) * 0.22;
        }
        if (plantCore) {
          plantCore.rotation.z += dt * 0.0004;
          plantCore.rotation.y += dt * 0.0002;
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
        // 3D dots are deliberately small.
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
        <div style="min-width:210px">
          <div style="font-weight:650;font-size:13px;letter-spacing:-0.01em;margin-bottom:3px;">${vendor.name}</div>
          <div style="font-size:11px;opacity:0.62;margin-bottom:9px;">${vendor.city}, ${vendor.state}</div>
          <div style="display:flex;gap:14px;font-size:11px;margin-bottom:${disruption ? "9px" : "0"};">
            <div><div style="opacity:0.55;">Reliability</div><div style="font-weight:600;">${vendor.reliability_score_0_100}%</div></div>
            <div><div style="opacity:0.55;">On-time</div><div style="font-weight:600;">${Math.round(vendor.on_time_rate * 100)}%</div></div>
            <div><div style="opacity:0.55;">Dues</div><div style="font-weight:600;">${vendor.dues_display}</div></div>
          </div>
          ${
            disruption && severity
              ? `<div style="border-top:1px solid rgba(255,255,255,0.1);padding-top:8px;">
                   <div style="display:inline-block;font-size:9px;font-weight:700;letter-spacing:0.06em;text-transform:uppercase;color:${SEVERITY_HEX[severity]};border:1px solid ${SEVERITY_HEX[severity]}55;border-radius:99px;padding:1px 7px;margin-bottom:5px;">${severity}</div>
                   <div style="font-size:11px;line-height:1.45;">${disruption.headline}</div>
                   <div style="font-size:11px;font-weight:650;margin-top:5px;color:${SEVERITY_HEX[severity]};">${disruption.exposure_total_display} exposure</div>
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
      <div className="glass-panel flex h-full items-center justify-center rounded-2xl text-sm text-ink-muted">
        NEXT_PUBLIC_MAPBOX_TOKEN is not set.
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.985 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
      className="glass-panel relative h-full overflow-hidden rounded-2xl"
    >
      <div ref={containerRef} className="h-full w-full" />

      {/* Vignette so the map edges melt into the page instead of hard-cropping */}
      <div
        className="pointer-events-none absolute inset-0 rounded-2xl"
        style={{ boxShadow: "inset 0 0 90px 24px rgba(7,9,16,0.75)" }}
      />

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.35, duration: 0.5 }}
        className="glass pointer-events-none absolute top-4 left-4 rounded-2xl px-4 py-3"
      >
        <p className="text-[0.625rem] font-semibold tracking-[0.14em] text-ink-faint uppercase">Supply network</p>
        <p className="mt-1 text-2xl leading-none font-semibold text-ink tabular-money">{vendors.length}</p>
        <p className="mt-1 text-[0.6875rem] text-ink-muted">
          vendors · <span className="text-accent-strong">{liveCount} live</span>
        </p>
      </motion.div>

      <motion.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.45, duration: 0.5 }}
        className="glass pointer-events-none absolute bottom-4 left-4 rounded-2xl px-4 py-3 text-xs text-ink-muted"
      >
        <p className="mb-2.5 text-[0.625rem] font-semibold tracking-[0.14em] text-ink uppercase">Legend</p>
        {(["critical", "elevated", "moderate"] as SeverityTier[]).map((tier) => (
          <div key={tier} className="mb-1.5 flex items-center gap-2.5">
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: SEVERITY_HEX[tier], boxShadow: `0 0 9px ${SEVERITY_HEX[tier]}` }}
            />
            <span className="capitalize">{tier}</span>
            <span className="text-ink-faint">
              {tier === "critical" ? "≥ ₹1Cr" : tier === "elevated" ? "≥ ₹25L" : "< ₹25L"}
            </span>
          </div>
        ))}
        <div className="mt-2.5 flex items-center gap-2.5 border-t border-white/10 pt-2.5">
          <span
            className="h-2 w-2 rotate-45"
            style={{ background: "#f7c163", boxShadow: "0 0 9px #f7c163" }}
          />
          Chakan plant
        </div>
        <div className="mt-1.5 flex items-center gap-2.5">
          <span className="h-2 w-2 rounded-full bg-gradient-to-r from-rose-500 to-emerald-400" />
          Vendor · reliability
        </div>
      </motion.div>
    </motion.div>
  );
}
