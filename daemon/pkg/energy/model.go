// This file implements the energy model for one satellite. It has two separate jobs:

// Generation: How many watts the solar panel produces from sunlight.
// Consumption: How many watts the satellite uses, based on its CPU utilization
// and (for the component model) its downlink transmission to a ground station.

// The important design idea is that these are models, not the simulation itself. They take inputs and return a number. 
// They do not know about Docker, satellites, or the rest of OpenSN.

//
// Design notes:
//   - Generation and consumption are separate, independently swappable
//     strategy interfaces (Strategy pattern) — a new generation model does
//     not require touching consumption code, and vice versa.
//   - Both are pure functions: given the same inputs, they always return
//     the same output, with no side effects and no hidden state. This makes
//     them trivially unit-testable without a running simulation, a real
//     etcd instance, or any containers.
//   - Sun-incidence angle (gamma) is NOT computed here. It is computed in
//     Python (pyephem) from the satellite's existing Position, and arrives
//     as part of model.SolarInput. This package only does the physics that
//     doesn't require orbital/solar geometry libraries.
package energy

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

// Solar Constant refers to the power of the Sun at the Earth, per square metre 
// So if a panel is 1 m^2 and is perfectly efficient and pointed directly at Sun, starting theoretical input would be 1361 W
// before accounting for efficiency and angle.
const SolarConstantWPerM2 = 1361.0 // B0, W/m^2 at 1 AU, fixed

// GenerationModel computes instantaneous generated power (Watts) for one
// satellite, given its static hardware spec and the current sun-incidence
// angle. Implementations must be pure functions (no I/O, no mutation)
// using an interface cuz might have different models later (Extensible)
type GenerationModel interface {
	Generate(spec PowerSpecInput, sunAngleRad float64) float64
}

// ConsumptionInput is the per-tick workload of one satellite.
type ConsumptionInput struct {
	Utilization      float64 // u(t), 0..1, the DVFS policy uses it to pick the CPU frequency
	HasGroundContact bool    // Ic(t), true if a ground station link is up
	TxRateBps        float64 // R(t), downlink rate, only used when HasGroundContact is true
}

// ConsumptionModel computes instantaneous consumed power (Watts) for one
// satellite, given its static hardware spec and its current workload.
type ConsumptionModel interface {
	Consume(spec PowerSpecInput, in ConsumptionInput) float64
}

// PowerSpecInput mirrors model.PowerSpec. Declared separately here so this
// package has no import dependency on the model package's other unrelated
// types. (Separation of Responsibilities)
type PowerSpecInput struct {
	PanelAreaM2      float64
	CellEfficiency   float64
	SystemEfficiency float64
	IdlePowerW       float64 // platform power P_a
	MaxPowerW        float64

	SensorPowerW     float64
	AlphaDVFS        float64
	MaxFrequencyHz   float64
	MinFrequencyHz   float64 // lowest CPU frequency the DVFS policy may pick
	StaticPowerW     float64 // c2: constant (static) power of the on-board computer, always drawn
	BandwidthHz      float64
	ChannelGainRatio float64
}

// ReflectivityLoss is a standard empirical estimate for angle-dependent
// panel-surface reflectivity loss (rho(gamma)). 
// Claude came up with it. THIS IS A PLACEHOLDER! FIND SOMETHING RIGOROUS:

//   rho(gamma) = rho0 + (1 - rho0) * sin(gamma)^n
//
// rho0 ~ 0.04 (typical AR-coated space-grade cell reflectance at normal
// incidence), n = 5 (reflectivity stays low until fairly grazing angles,
// then rises sharply) - standard shape used in solar-panel power-loss
// approximations.
func ReflectivityLoss(sunAngleRad float64) float64 {
	const rho0 = 0.04
	const n = 5.0
	return rho0 + (1-rho0)*math.Pow(math.Sin(sunAngleRad), n)
}

// FullPowerModel implements the equation from the energy extension design:
//
//   P = A * eta_sc * B0 * eta_sys * cos(gamma) * (1 - rho(gamma))
//
// ReflectivityFn is injectable so a different reflectivity estimate can be
// swapped in (e.g. a lookup-table model, or a per-material formula) without
// changing this struct's Generate logic (Open/Closed principle)
type FullPowerModel struct {
	ReflectivityFn func(sunAngleRad float64) float64
}

// NewFullPowerModel returns a FullPowerModel using the standard
// ReflectivityLoss estimate. Use this unless you have a specific reason to
// inject a different reflectivity function.
func NewFullPowerModel() *FullPowerModel {
	return &FullPowerModel{ReflectivityFn: ReflectivityLoss}
}

func (m *FullPowerModel) Generate(spec PowerSpecInput, sunAngleRad float64) float64 {
	// Satellite is past the terminator / sun below panel plane: no
	// generation. cos(gamma) would go negative past 90 degrees, which is
	// not physically meaningful here — clamp to zero rather than letting
	// negative "generation" leak into downstream sums.
	//
	// Uses a small epsilon rather than a strict `<= 0` comparison:
	// float64 trig functions don't return exact zero at pi/2 (e.g.
	// math.Cos(math.Pi/2) is ~6e-17, not 0, due to floating-point
	// representation of pi/2 itself) — a strict comparison would let a
	// physically-zero case sneak through as a tiny nonzero generation
	// value instead of clamping cleanly.
	const epsilon = 1e-9
	cosGamma := math.Cos(sunAngleRad)
	if cosGamma <= epsilon {
		return 0
	}
	rho := m.ReflectivityFn(sunAngleRad)
	return spec.PanelAreaM2 *
		spec.CellEfficiency *
		SolarConstantWPerM2 *
		spec.SystemEfficiency *
		cosGamma *
		(1 - rho)
}

// LinearConsumptionModel implements:
//
//   P_consume(t) = P_idle + (P_max - P_idle) * u(t)
//
// utilization is expected in [0, 1]; values outside that range are clamped
// so a bad upstream u(t) value can't produce a negative or over-max power
// draw. Ground contact and tx rate are ignored by this model.
type LinearConsumptionModel struct{}

func NewLinearConsumptionModel() *LinearConsumptionModel {
	return &LinearConsumptionModel{}
}

func (m *LinearConsumptionModel) Consume(spec PowerSpecInput, in ConsumptionInput) float64 {
	u := in.Utilization
	if u < 0 {
		u = 0
	}
	if u > 1 {
		u = 1
	}
	return spec.IdlePowerW + (spec.MaxPowerW-spec.IdlePowerW)*u
}

// FrequencyPolicy decides which CPU frequency (in Hz) a satellite runs at,
// given how busy its CPU is. The power model only calls this one method, so
// any policy can be plugged in by writing a type that has it.
// The spec is passed in so one policy can serve satellites with different
// min/max frequencies.
type FrequencyPolicy interface {
	Frequency(spec PowerSpecInput, u float64) float64
}

// FrequencyBand is one step of a band policy.
// Example: {0.5, 0.5} means "while utilization is up to 50%, run at 50% of max frequency".
type FrequencyBand struct {
	MaxUtilization float64 // band applies while u <= this value (0..1)
	FreqRatio      float64 // fraction of max frequency used in this band (0..1)
}

// BandPolicy picks the frequency from utilization bands (not a one-to-one
// mapping from u to f). Bands must be sorted by MaxUtilization, lowest first.
// If u is above every band, the CPU runs at max frequency.
type BandPolicy struct {
	Bands []FrequencyBand
}

func (p *BandPolicy) Frequency(spec PowerSpecInput, u float64) float64 {
	ratio := 1.0 // above all bands: full speed
	for _, b := range p.Bands {
		if u <= b.MaxUtilization {
			ratio = b.FreqRatio
			break
		}
	}
	f := ratio * spec.MaxFrequencyHz
	// Keep the result between the satellite's min and max frequency
	return math.Max(spec.MinFrequencyHz, math.Min(spec.MaxFrequencyHz, f))
}

// FixedPolicy ignores utilization and always runs at one frequency.
// Use it when an external algorithm decides the frequency.
type FixedPolicy struct {
	Hz float64
}

func (p *FixedPolicy) Frequency(spec PowerSpecInput, u float64) float64 {
	return math.Max(spec.MinFrequencyHz, math.Min(spec.MaxFrequencyHz, p.Hz))
}

// ParseBandPolicy builds a BandPolicy from text like "0.5:0.5,1.0:1.0".
// Each pair is "utilization upper limit : fraction of max frequency".
func ParseBandPolicy(s string) (*BandPolicy, error) {
	var bands []FrequencyBand
	for _, part := range strings.Split(s, ",") {
		pair := strings.Split(strings.TrimSpace(part), ":")
		if len(pair) != 2 {
			return nil, fmt.Errorf("bad DVFS band %q, expected limit:ratio", part)
		}
		limit, err1 := strconv.ParseFloat(pair[0], 64)
		ratio, err2 := strconv.ParseFloat(pair[1], 64)
		if err1 != nil || err2 != nil || limit <= 0 || limit > 1 || ratio <= 0 || ratio > 1 {
			return nil, fmt.Errorf("bad DVFS band %q, both values must be in (0, 1]", part)
		}
		// Limits must go up, otherwise a later band could never be reached
		if len(bands) > 0 && limit <= bands[len(bands)-1].MaxUtilization {
			return nil, fmt.Errorf("DVFS band limits must increase, got %q", part)
		}
		bands = append(bands, FrequencyBand{MaxUtilization: limit, FreqRatio: ratio})
	}
	return &BandPolicy{Bands: bands}, nil
}

// ComponentConsumptionModel adds up the power of each part of the satellite:
//
//   P_consume = P_idle + P_sensor + P_IT + P_comm
//
//   P_IT   = c1 * f^3 * u + c2             where f = Policy(u) (DVFS)
//                                           c1 = AlphaDVFS, c2 = StaticPowerW
//   P_comm = (2^(R/B) - 1) / (h/N0)        only while a ground link is up
//
// P_idle is the rest of the platform (everything except the computer, the
// sensor and the radio). Total is capped at MaxPowerW, the hardware limit.
//
// P_idle: platform load of the satellite excluding the
// on-board computer (attitude control, thermal, telemetry, housekeeping).
// Corresponds to E_a in Li et al. (2021). Constant.
//
// c2: static power of the on-board computer, i.e. what it
// draws when powered on with no work (leakage, memory, board overhead).
// Static term of Arroba et al. (2017), simplified to a constant.

type ComponentConsumptionModel struct {
	Policy FrequencyPolicy // decides the CPU frequency from utilization
}

// NewComponentConsumptionModel takes the DVFS policy to use.
// A nil policy means no DVFS: the CPU always runs at max frequency.
func NewComponentConsumptionModel(policy FrequencyPolicy) *ComponentConsumptionModel {
	if policy == nil {
		policy = &BandPolicy{} // no bands = always max frequency
	}
	return &ComponentConsumptionModel{Policy: policy}
}

func (m *ComponentConsumptionModel) CommPower(spec PowerSpecInput, in ConsumptionInput) float64 {
	// Comm: only draws power while a ground station link is up
	if !in.HasGroundContact {
		return 0
	}
	rate := math.Max(0, in.TxRateBps)
	return (math.Pow(2, rate/spec.BandwidthHz) - 1) / spec.ChannelGainRatio
}

func (m *ComponentConsumptionModel) Consume(spec PowerSpecInput, in ConsumptionInput) float64 {
	// IT (on-board computer): the policy picks the frequency, dynamic power
	// grows with f^3 and u, and a constant static part is always drawn
	u := math.Max(0, math.Min(1, in.Utilization))
	freq := m.Policy.Frequency(spec, u)
	itW := spec.AlphaDVFS*freq*freq*freq*u + spec.StaticPowerW

	commW := m.CommPower(spec, in)

	total := spec.IdlePowerW + spec.SensorPowerW + itW + commW
	if spec.MaxPowerW > 0 && total > spec.MaxPowerW {
		total = spec.MaxPowerW
	}
	return total
}