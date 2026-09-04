/* V0.89-G4.1 design-derived parameter authority.
 *
 * This module owns relationships that are useful for an immediate Studio preview
 * but are not authoritative Motor-CAD readback.  Keeping them here prevents the
 * editor, winding renderer and geometry renderer from each inventing a different
 * approximation.
 */
(() => {
  const finite = (value, fallback = null) => {
    const parsed = Number(value);
    return value !== null && value !== '' && Number.isFinite(parsed) ? parsed : fallback;
  };
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

  function slotDimensions(values = {}, motorObject = null) {
    const slot = motorObject?.stator?.slot || {};
    const opening = Math.max(0, finite(slot.opening_mm ?? values.slot_opening, 0));
    const width = Math.max(opening, finite(slot.width_mm ?? values.slot_width, opening));
    const depth = Math.max(0, finite(slot.depth_mm ?? values.slot_depth, 0));
    const corner = Math.max(0, finite(slot.corner_radius_mm ?? values.slot_corner_radius, 0));
    return {opening, width, depth, corner};
  }

  function approximateSlotArea(values = {}, motorObject = null) {
    const {opening, width, depth, corner} = slotDimensions(values, motorObject);
    if (!(width > 0 && depth > 0)) return null;
    // The structured parameter set does not expose the complete native slot polygon.
    // Use a stable trapezoid-minus-corners approximation only for relative updates.
    const neck = Math.max(opening, width * 0.45);
    const gross = depth * (width + neck) / 2;
    const cornerLoss = Math.min(gross * 0.18, Math.PI * corner * corner * 0.5);
    const usable = (gross - cornerLoss) * 0.86;
    return Number.isFinite(usable) && usable > 0 ? usable : null;
  }

  function estimateSlotFill(values = {}, baselineValues = {}, options = {}) {
    const turns = finite(values.turns_per_coil);
    const baselineTurns = finite(baselineValues.turns_per_coil);
    const baselineFill = finite(baselineValues.slot_fill_factor);
    if (!(turns > 0 && baselineTurns > 0 && baselineFill > 0)) return null;

    const currentArea = approximateSlotArea(values, options.motorObject);
    const baselineArea = approximateSlotArea(baselineValues, options.baselineMotorObject);
    const strands = Math.max(1, finite(values.strands_in_hand, 1));
    const baselineStrands = Math.max(1, finite(baselineValues.strands_in_hand, 1));
    const turnRatio = turns / baselineTurns;
    const strandRatio = strands / baselineStrands;
    const slotAreaRatio = currentArea && baselineArea ? baselineArea / currentArea : 1;
    const raw = baselineFill * turnRatio * strandRatio * slotAreaRatio;
    if (!Number.isFinite(raw) || raw <= 0) return null;
    return {
      value: Number(clamp(raw, 0.001, 2).toFixed(8)),
      raw,
      turn_ratio: turnRatio,
      strand_ratio: strandRatio,
      slot_area_ratio: slotAreaRatio,
      assumption: 'fixed_conductor_and_insulation',
      authority: 'studio_relative_estimate',
    };
  }

  function conductorMarkerPlan(turnsValue, options = {}) {
    const turns = Math.max(1, Math.round(finite(turnsValue, 1)));
    const maxMarkers = Math.max(1, Math.round(finite(options.maxMarkers, 96)));
    const markerCount = Math.min(turns, maxMarkers);
    return {
      turns,
      marker_count: markerCount,
      turns_per_marker: turns / markerCount,
      exact: turns <= maxMarkers,
    };
  }

  function ipmMagnetLayout(options = {}) {
    const radius = Math.max(1, finite(options.radiusPx, 1));
    const polePitch = clamp(finite(options.polePitchDeg, 45), 4, 180);
    const thickness = Math.max(1, finite(options.thicknessPx, 4));
    const requestedWidth = Math.max(1, finite(options.widthPx, 12));
    // Keep every V pair inside its pole sector.  The bridge is deliberately wider
    // than the two rounded inner corners, so the preview never paints one leg over
    // the other and never implies a zero-thickness iron bridge.
    const sectorHalfChord = radius * Math.sin((polePitch * Math.PI / 180) / 2);
    const bridge = Math.max(thickness * 1.15, finite(options.bridgePx, thickness * 1.15));
    const maximumWidth = Math.max(8, sectorHalfChord * 0.82 - bridge / 2);
    const width = Math.min(requestedWidth, maximumWidth);
    return {
      width_px: width,
      bridge_px: bridge,
      left_x: -width - bridge / 2,
      right_x: bridge / 2,
      capped: width + 1e-6 < requestedWidth,
      maximum_width_px: maximumWidth,
    };
  }

  window.MCSDesignDerivedParameters = Object.freeze({
    approximateSlotArea,
    estimateSlotFill,
    conductorMarkerPlan,
    ipmMagnetLayout,
  });
})();
