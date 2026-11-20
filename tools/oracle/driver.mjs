// Runs the official SYNTAX calculator's own JavaScript (tools/oracle/official/frameset.js) over
// JSON cases and prints the official totals. The official code runs inside a node:vm context that
// exposes no require, process, fetch or network: only inert stubs for the page objects it touches.
//
//   node driver.mjs < cases.json > results.json
//   node driver.mjs --selftest-sandbox          (prints what the sandbox exposes)
//
// The official form is a UI: handlers are replayed in the order the real form calls them
// (form.js / lesion_segments.htm), so the totals are what the calculator would show.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const officialJs = fs.readFileSync(path.join(here, "official", "frameset.js"), "latin1");
const script = new vm.Script(officialJs, { filename: "frameset.js" });

function newSandbox() {
  const box = {
    alert() {},
    document: { getElementById: () => null, write() {}, getElementsByName: () => [] },
  };
  box.window = box;
  box.parent = box;
  box.top = box;
  box.self = box;
  box.frames = new Proxy({}, { get: () => ({ window: { location: {} }, document: { getElementById: () => null } }) });
  const ctx = vm.createContext(box);
  script.runInContext(ctx, { timeout: 5000 });
  // Neutralise the functions that only drive the page frames.
  vm.runInContext("setFrameUrl = function () {}; setHeaderText = function () {};", ctx);
  return ctx;
}

if (process.argv.includes("--selftest-sandbox")) {
  const ctx = vm.createContext({});
  const probe = (name) => vm.runInContext(`typeof ${name}`, ctx);
  process.stdout.write(JSON.stringify({
    require: probe("require"), process: probe("process"), fetch: probe("fetch"),
    XMLHttpRequest: probe("XMLHttpRequest"),
  }));
  process.exit(0);
}

const RUN = `
function __idx(id) {
  for (var i = 0; i < meDiffuseTableArray.length; i++) if (meDiffuseTableArray[i][1] === id) return i;
  throw new Error("unknown segment " + id);
}
function __run(c) {
  var dom = c.dominance === "co-dominant" ? c.scoring_dominance : c.dominance;
  setDominance(dom);
  var ME = { checked: true };
  for (var k = 0; k < c.lesions.length; k++) {
    var L = c.lesions[k];
    if (k > 0) NextLesion();
    L.segments.forEach(function (s) { SetSegmentsInvolved(__idx(s), meCurrentLesion, ME); });
    SegmentsInvolvedSave();
    CalculateTotalOcclusion();                       // lesion_segments.htm Continue()
    var occ = L.occlusion === true;
    SetTotalOcclusion(occ ? 1 : 0);                  // Question4
    if (occ) {
      resetTotalOcclusionScore();                    // Question4I
      SetIndicateSegmentNumber(__idx(L.first_segment), ME);
      SetAgeOfTO({ no: 0, yes: 1, unknown: 2 }[L.age_over_3_months]);   // Question4II
      SetBluntStump(L.blunt_stump ? 1 : 0);          // Question4III
      setBridging(L.bridging ? 1 : 0);               // Question4IV
      var mostProx = getMostProximalSegmentNumber(), row = null;
      for (var i = 0; i < meSegmentVisualizedTableHelp.length; i++)
        if (meSegmentVisualizedTableHelp[i][0] == mostProx) row = meSegmentVisualizedTableHelp[i];
      if (row && row[4] == "1") {                    // Question4V (only when the table is shown)
        setVisualizedByMainSegment(mostProx);
        setVisualizedByContrast(L.beyond_first_visualized);
      } else {
        setVisualizedByMainSegment("-1");
        setVisualizedByContrast("Skipped");
      }
      setSideBranch({ no: 0, small: 1, large: 2, both: 3 }[L.side_branch]);   // Question4VI
    }
    var asked = !(occ && (L.side_branch === "no" || L.side_branch === "small"));
    if (asked) {                                     // Question5 / Question6
      SetTrifurcation(L.trifurcation);
      if (L.trifurcation === 0) {
        SetBifurcation(L.bifurcation === "none" ? "" : L.bifurcation);
        if (L.bifurcation !== "none") SetBifurcationAngulation(L.bifurcation_angle_lt70 ? 1 : 0);
      }
    }
    SetAortaOstialLesion(Question7Enabled() ? (L.aorto_ostial ? 1 : 0) : 0);   // Question7
    SetSevereTorTuosity(L.severe_tortuosity ? 1 : 0);                           // Question8
    if (!occ) SetLength(L.length_gt20 ? 1 : 0);                                 // Question9
    SetHeavycalcification(L.heavy_calcification ? 1 : 0);                       // Question10
    SetThrombus(L.thrombus ? 1 : 0);                                            // Question11
    setLesionAsCompleted();
  }
  var per = meScorePerLesion.slice(0, c.lesions.length);
  var before = GetScore();
  c.diffuse_segments.forEach(function (s) { setDiffuseDisease(__idx(s), ME); });
  return { total: GetScore(), per_lesion: per, diffuse: GetScore() - before };
}
`;

const input = fs.readFileSync(0, "utf8");
const cases = JSON.parse(input);
const results = cases.map((c) => {
  try {
    const ctx = newSandbox();
    vm.runInContext(RUN, ctx);
    ctx.__case = c;
    return vm.runInContext("__run(__case)", ctx, { timeout: 5000 });
  } catch (e) {
    return { error: String(e && e.message ? e.message : e) };
  }
});
process.stdout.write(JSON.stringify(results));
