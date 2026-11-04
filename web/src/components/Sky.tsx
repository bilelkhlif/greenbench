const SCENES = new Set(["home", "workloads", "campaigns", "results", "recommendations", "protocol", "roadmap"]);

/** Fixed night-sky backdrop. Each page has its own scene; the colours and the orb glide between scenes. */
export function Sky({ scene }: { scene: string }) {
  return (
    <div className="sky" data-scene={SCENES.has(scene) ? scene : "home"} aria-hidden="true">
      <div className="stars" />
      <div className="stars s2" />
      <div className="aurora">
        <div className="band" />
        <div className="band b2" />
      </div>
      <div className="orb" />
      <div className="horizon" />
    </div>
  );
}
