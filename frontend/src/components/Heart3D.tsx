import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { FBXLoader } from 'three/examples/jsm/loaders/FBXLoader.js';

interface Heart3DProps {
  className?: string;
}

export const Heart3D: React.FC<Heart3DProps> = ({
  className = '',
}) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // 1. RENDERER SETUP
    const width = container.clientWidth || window.innerWidth;
    const height = container.clientHeight || window.innerHeight;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(36, width / height, 0.1, 100);
    camera.position.set(0, 0, 7.5);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ 
      antialias: true, 
      alpha: true,
      powerPreference: 'high-performance'
    });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    container.appendChild(renderer.domElement);

    // 2. BRIGHT STUDIO LIGHTING FOR PURE WHITE BACKGROUND
    const ambientLight = new THREE.AmbientLight(0xffffff, 2.2);
    scene.add(ambientLight);

    const mainLight = new THREE.DirectionalLight(0xffffff, 2.8);
    mainLight.position.set(6, 9, 8);
    scene.add(mainLight);

    const rimLight = new THREE.DirectionalLight(0xe2e8f0, 2.0);
    rimLight.position.set(-6, -3, -5);
    scene.add(rimLight);

    const mouseTrackingLight = new THREE.PointLight(0xffffff, 2.5, 14);
    mouseTrackingLight.position.set(0, 0, 5);
    scene.add(mouseTrackingLight);

    const softFill = new THREE.DirectionalLight(0xd4d4d8, 1.4);
    softFill.position.set(0, -6, 4);
    scene.add(softFill);

    // 3. ROOT CENTERED GROUP
    const rootGroup = new THREE.Group();
    rootGroup.position.set(0, 0, 0);
    scene.add(rootGroup);

    // Inner Model Pivot to guarantee perfect center-of-mass alignment
    const modelPivot = new THREE.Group();
    rootGroup.add(modelPivot);

    // 4. CLEAN LIGHT-CHARCOAL AXIS RING (Subtle on white)
    const orbitGeo = new THREE.RingGeometry(2.5, 2.52, 64);
    const orbitMat = new THREE.MeshBasicMaterial({
      color: 0x94a3b8,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.35,
      depthWrite: false,
    });
    const orbitRing = new THREE.Mesh(orbitGeo, orbitMat);
    orbitRing.rotation.x = Math.PI / 3;
    orbitRing.rotation.y = Math.PI / 8;
    rootGroup.add(orbitRing);

    // 5. LOAD TEXTURES
    const textureLoader = new THREE.TextureLoader();
    const baseColor = textureLoader.load('/models/heart/textures/hart_UV_low01_BaseColor.hart_UV_low_defaultMat.png');
    const normalMap = textureLoader.load('/models/heart/textures/hart_UV_low01_Normal.hart_UV_low_defaultMat.png');
    const roughnessMap = textureLoader.load('/models/heart/textures/hart_UV_low01_Roughness.hart_UV_low_defaultMat.png');
    const metalnessMap = textureLoader.load('/models/heart/textures/hart_UV_low01_Metalness.hart_UV_low_defaultMat.png');

    baseColor.colorSpace = THREE.SRGBColorSpace;
    baseColor.generateMipmaps = true;
    baseColor.minFilter = THREE.LinearMipmapLinearFilter;

    const heartMaterial = new THREE.MeshStandardMaterial({
      map: baseColor,
      normalMap: normalMap,
      roughnessMap: roughnessMap,
      metalnessMap: metalnessMap,
      roughness: 0.35,
      metalness: 0.1,
      emissive: 0x111111,
      emissiveIntensity: 0.15,
    });

    // 6. LOAD FBX MODEL WITH EXACT CENTER OF MASS ALIGNMENT
    const fbxLoader = new FBXLoader();
    fbxLoader.load(
      '/models/heart/Heart.fbx',
      (fbx) => {
        const box = new THREE.Box3().setFromObject(fbx);
        const center = new THREE.Vector3();
        const size = new THREE.Vector3();
        box.getCenter(center);
        box.getSize(size);

        // Center exactly at 0, 0, 0
        fbx.position.set(-center.x, -center.y, -center.z);

        const maxAxis = Math.max(size.x, size.y, size.z);
        const baseScale = maxAxis > 0 ? 2.9 / maxAxis : 0.02;
        modelPivot.scale.setScalar(baseScale);

        fbx.traverse((child) => {
          if ((child as THREE.Mesh).isMesh) {
            const mesh = child as THREE.Mesh;
            mesh.material = heartMaterial;
            mesh.castShadow = false;
            mesh.receiveShadow = false;
          }
        });

        // Natural resting angle
        modelPivot.rotation.set(0.15, 0.4, -0.1);
        modelPivot.add(fbx);
      },
      undefined,
      (err) => {
        console.warn('Fallback procedural heart loaded:', err);
        const geo = new THREE.SphereGeometry(1.25, 48, 48);
        const pos = geo.attributes.position;
        const v = new THREE.Vector3();
        for (let i = 0; i < pos.count; i++) {
          v.fromBufferAttribute(pos, i);
          let x = v.x, y = v.y, z = v.z;
          if (y < 0) {
            const taper = 1.0 + y * 0.45;
            x *= Math.max(0.2, taper);
            z *= Math.max(0.2, taper);
            y *= 1.25;
          } else {
            const cleft = 1.0 - Math.exp(-Math.pow(x * 1.8, 2)) * 0.35;
            y *= cleft * 1.1;
            x *= 1.15;
          }
          pos.setXYZ(i, x, y, z);
        }
        geo.computeVertexNormals();
        const mat = new THREE.MeshStandardMaterial({
          color: 0x475569,
          roughness: 0.35,
          metalness: 0.4,
          emissive: 0x1e293b,
          emissiveIntensity: 0.3,
        });
        const mesh = new THREE.Mesh(geo, mat);
        modelPivot.add(mesh);
      }
    );

    // 7. HIGHLY REACTIVE MOUSE & DRAG INTERACTION
    let targetRotX = 0;
    let targetRotY = 0;
    let targetPosX = 0;
    let targetPosY = 0;

    let currentRotX = 0;
    let currentRotY = 0;
    let currentPosX = 0;
    let currentPosY = 0;

    let isDragging = false;
    let previousMousePosition = { x: 0, y: 0 };
    let dragVelocity = { x: 0, y: 0 };
    let dragRotY = 0;
    let dragRotX = 0;

    const handleMouseMove = (e: MouseEvent) => {
      const nx = (e.clientX / window.innerWidth - 0.5) * 2;
      const ny = (e.clientY / window.innerHeight - 0.5) * 2;

      targetRotY = nx * 1.1;
      targetRotX = ny * 0.65;

      targetPosX = nx * 0.45;
      targetPosY = -ny * 0.35;

      mouseTrackingLight.position.x = nx * 6;
      mouseTrackingLight.position.y = -ny * 5;

      if (isDragging) {
        const deltaMove = {
          x: e.clientX - previousMousePosition.x,
          y: e.clientY - previousMousePosition.y,
        };

        dragVelocity = {
          x: deltaMove.x * 0.008,
          y: deltaMove.y * 0.008,
        };

        dragRotY += dragVelocity.x;
        dragRotX += dragVelocity.y;

        previousMousePosition = {
          x: e.clientX,
          y: e.clientY,
        };
      }
    };

    const handleMouseDown = (e: MouseEvent) => {
      isDragging = true;
      previousMousePosition = {
        x: e.clientX,
        y: e.clientY,
      };
    };

    const handleMouseUp = () => {
      isDragging = false;
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mousedown', handleMouseDown);
    window.addEventListener('mouseup', handleMouseUp);

    const handleResize = () => {
      if (!container) return;
      const w = container.clientWidth || window.innerWidth;
      const h = container.clientHeight || window.innerHeight;
      if (w === 0 || h === 0) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', handleResize);

    // 8. HIGH-PERFORMANCE REACTIVE ANIMATION LOOP
    let animId: number;
    let lastTime = performance.now();

    const animate = (now: number) => {
      animId = requestAnimationFrame(animate);

      const delta = Math.min((now - lastTime) / 1000, 0.1);
      lastTime = now;

      if (!isDragging) {
        dragVelocity.x *= 0.94;
        dragVelocity.y *= 0.94;
        dragRotY += dragVelocity.x;
        dragRotX += dragVelocity.y;
      }

      currentRotX += (targetRotX + dragRotX - currentRotX) * 0.08;
      currentRotY += (targetRotY + dragRotY - currentRotY) * 0.08;
      currentPosX += (targetPosX - currentPosX) * 0.08;
      currentPosY += (targetPosY - currentPosY) * 0.08;

      rootGroup.rotation.y = currentRotY;
      rootGroup.rotation.x = currentRotX;
      rootGroup.rotation.z = -currentRotY * 0.18;

      rootGroup.position.x = currentPosX;
      rootGroup.position.y = currentPosY;
      rootGroup.position.z = Math.abs(currentRotY) * 0.2;

      orbitRing.rotation.z += delta * 0.2;

      renderer.render(scene, camera);
    };

    animId = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('mouseup', handleMouseUp);
      window.removeEventListener('resize', handleResize);
      if (renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
      renderer.dispose();
      scene.clear();
    };
  }, []);

  return (
    <div className={`w-full h-full relative pointer-events-none select-none ${className}`}>
      <div 
        ref={containerRef} 
        className="absolute inset-0 w-full h-full pointer-events-auto cursor-grab active:cursor-grabbing" 
      />
    </div>
  );
};
