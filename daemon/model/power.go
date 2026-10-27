package model

// PowerSpec holds the static, per-satellite hardware specification used by
// my Power Model. These values come from Instance.Extra (parsed from
// strings) at topology-load time and do not change during the simulation -
// same lifecycle as TLE data.
//
// Extra key names (add to instance_types.py on the Python side too, so both
// languages agree on the string keys used in Instance.Extra):
//   panel_area_m2       -> PanelAreaM2
//   cell_efficiency     -> CellEfficiency
//   system_efficiency   -> SystemEfficiency
//   idle_power_w        -> IdlePowerW
//   max_power_w         -> MaxPowerW
//   sensor_power_w      -> SensorPowerW
//   alpha_dvfs          -> AlphaDVFS
//   max_frequency_hz    -> MaxFrequencyHz
//   min_frequency_hz    -> MinFrequencyHz
//   static_power_w      -> StaticPowerW
//   bandwidth_hz        -> BandwidthHz
//   channel_gain_ratio  -> ChannelGainRatio
type PowerSpec struct {
	PanelAreaM2      float64 `json:"panel_area_m2"`
	CellEfficiency   float64 `json:"cell_efficiency"`
	SystemEfficiency float64 `json:"system_efficiency"`
	IdlePowerW       float64 `json:"idle_power_w"`       // P_a, platform load excluding computer, sensor and radio
	MaxPowerW        float64 `json:"max_power_w"`

	// Li et al. Hardware Constants
	SensorPowerW     float64 `json:"sensor_power_w"`     // P_sen, constant camera power
	BandwidthHz      float64 `json:"bandwidth_hz"`       // B
	ChannelGainRatio float64 `json:"channel_gain_ratio"` // h / N0

	// On-board computer (DVFS): P_IT = c1 * f^3 * u + c2
	AlphaDVFS      float64 `json:"alpha_dvfs"`       // c1, dynamic power coefficient
	StaticPowerW   float64 `json:"static_power_w"`   // c2, constant power whenever the computer is on
	MaxFrequencyHz float64 `json:"max_frequency_hz"` // f_max, highest CPU frequency
	MinFrequencyHz float64 `json:"min_frequency_hz"` // f_min, lowest CPU frequency
}

// SolarInput is written by the Python Topology Configurator every tick
// (pyephem computes the sun-incidence angle from the satellite's existing
// position — no orbital/solar geometry math happens in Go). This is the
// power-model equivalent of Position: computed in Python, pushed to the
// daemon, consumed by a Go module.
type SolarInput struct {
	SunAngleRad float64 `json:"sun_angle_rad"` // gamma, radians, 0 = sun directly overhead panel
	Utilization float64 `json:"utilization"` // u(t), measured CPU utilization 0..1, used by the DVFS policy
	Timestamp   float64 `json:"timestamp"`   // sample time, must match Python's key name exactly
	
	HasGroundContact bool    `json:"has_ground_contact"` // Ic(t)
	TxRateBps        float64 `json:"tx_rate_bps"`        // R(t)
}

// PowerStatus is the computed, per-tick result written by PowerModule
// (Go side) after combining PowerSpec + SolarInput. This is what the web
// console / KV DB consumers should read for "current" power state.
type PowerStatus struct {
	GeneratedPowerW float64 `json:"generated_power_w"`
	ConsumedPowerW  float64 `json:"consumed_power_w"`
	NetPowerW       float64 `json:"net_power_w"` // generated - consumed, convenience field
	BatteryPercent  float64 `json:"battery_percent"`
}
