// This is the orchestration layer of the energy extension.
// It is the piece that connects all the other pieces together and runs them repeatedly

package module

import (
	"NodeDaemon/config"
	"NodeDaemon/model"
	"NodeDaemon/pkg/energy"
	"NodeDaemon/pkg/synchronizer"
	"NodeDaemon/share/key"
	"NodeDaemon/share/signal"
	"strconv"
	"sync"
	"time"

	"github.com/sirupsen/logrus"
)

// OpenSN instance model already has an Extra field CHECK!!!
// Extra keys read from Instance.Extra for satellite power specs. Keep these
// string literals in sync with the equivalent constants on the Python side
// (instance_types.py), same convention as EX_TLE0_KEY etc.
const (
	ExPanelAreaKey      = "panel_area_m2"
	ExCellEfficiencyKey = "cell_efficiency"
	ExSystemEffKey      = "system_efficiency"
	ExIdlePowerKey      = "idle_power_w"
	ExMaxPowerKey       = "max_power_w"
	ExSensorPowerKey      = "sensor_power_w"
	ExAlphaDVFSKey        = "alpha_dvfs"
	ExMaxFrequencyKey     = "max_frequency_hz"
	ExBandwidthKey        = "bandwidth_hz"
	ExChannelGainRatioKey = "channel_gain_ratio"
	ExBatteryCapacityWhKey    = "battery_capacity_wh"    // size this to survive eclipse
	ExBatteryThresholdPercentKey = "battery_threshold_percent" // e.g. "10" for 10%
)

type PowerModule struct {
	Base
}

type batteryConfig struct {
	CapacityWh       float64
	ThresholdPercent float64
}

func CreatePowerModule() *PowerModule {
	return &PowerModule{
		Base{
			sigChan:    make(chan int),
			errChan:    make(chan error),
			wg:         new(sync.WaitGroup),
			daemonFunc: powerDaemonFunc,
			running:    false,
			ModuleName: "PowerModule",
		},
	}
}

// specFromExtra parses a satellite's power hardware spec out of its Extra
// map. Returns ok=false (not an error) when any required key is missing —
// this is how ground-station / router instances, which have no power spec,
// are silently skipped rather than needing an explicit type check against
// a satellite-type constant.
func specFromExtra(extra map[string]string) (energy.PowerSpecInput, bool) {
	keys := []string{
		ExPanelAreaKey, ExCellEfficiencyKey, ExSystemEffKey, ExIdlePowerKey, ExMaxPowerKey,
		ExSensorPowerKey, ExAlphaDVFSKey, ExMaxFrequencyKey, ExBandwidthKey, ExChannelGainRatioKey,
	}
	values := make(map[string]float64, len(keys))
	for _, k := range keys {
		raw, present := extra[k]
		if !present {
			return energy.PowerSpecInput{}, false
		}
		parsed, err := strconv.ParseFloat(raw, 64)
		if err != nil {
			logrus.Warnf("Power spec key %s has non-numeric value %q, skipping instance", k, raw)
			return energy.PowerSpecInput{}, false
		}
		values[k] = parsed
	}
	return energy.PowerSpecInput{
		PanelAreaM2:      values[ExPanelAreaKey],
		CellEfficiency:   values[ExCellEfficiencyKey],
		SystemEfficiency: values[ExSystemEffKey],
		IdlePowerW:       values[ExIdlePowerKey],
		MaxPowerW:        values[ExMaxPowerKey],
		SensorPowerW:     values[ExSensorPowerKey],
		AlphaDVFS:        values[ExAlphaDVFSKey],
		MaxFrequencyHz:   values[ExMaxFrequencyKey],
		BandwidthHz:      values[ExBandwidthKey],
		ChannelGainRatio: values[ExChannelGainRatioKey],
	}, true
}

// Checks for and extracts the battery capacity and threshold parameters from the instance's extra map.
func batteryConfigFromExtra(extra map[string]string) (batteryConfig, bool) {
	keys := []string{ExBatteryCapacityWhKey, ExBatteryThresholdPercentKey}
	values := make(map[string]float64, len(keys))
	for _, k := range keys {
		raw, present := extra[k]
		if !present {
			return batteryConfig{}, false
		}
		parsed, err := strconv.ParseFloat(raw, 64)
		if err != nil {
			logrus.Warnf("Battery config key %s has non-numeric value %q, skipping battery calc for instance", k, raw)
			return batteryConfig{}, false
		}
		values[k] = parsed
	}
	return batteryConfig{
		CapacityWh:       values[ExBatteryCapacityWhKey],
		ThresholdPercent: values[ExBatteryThresholdPercentKey],
	}, true
}

func powerDaemonFunc(sigChan chan int, errChan chan error) {
	generationModel := energy.NewFullPowerModel()
	consumptionModel := energy.NewComponentConsumptionModel()

	// Battery state, persists across ticks, keyed by InstanceID.
	// Stored in Wh (real energy units) — NOT percent. Percent is derived
	// only at write-time for display/threshold reporting.
	batteryWh := make(map[string]float64)
	lastTimestamp := make(map[string]float64)

	for {
		select {
		case sig := <-sigChan:
			if sig == signal.STOP_SIGNAL {
				return
			}
		case <-time.After(time.Duration(config.GlobalConfig.App.MonitorInterval) * time.Second):
			// tick, same cadence as MonitorModule — power state is cheap to
			// recompute and should stay roughly in sync with other status
			// data rather than running on its own unrelated interval
		}
		
		// What instances are running on this node? Eg. Satellites/Ground Stations
		instances, err := synchronizer.GetInstanceList(key.NodeIndex)
		if err != nil {
			logrus.Errorf("PowerModule: get instance list of node %d error: %s", key.NodeIndex, err.Error())
			errChan <- err
			continue
		}
		logrus.Infof("PowerModule DEBUG: node_index=%d instances_found=%d", key.NodeIndex, len(instances))
		
		// Get sun angle and u(t) from etcd database
		solarInputs, err := synchronizer.GetAllInstanceSolarInput()
		if err != nil {
			logrus.Errorf("PowerModule: get solar input error: %s", err.Error())
			errChan <- err
			continue
		}

		for _, instance := range instances {
			spec, ok := specFromExtra(instance.Extra)
			if !ok {
				continue // not a power-modeled instance (e.g. ground station)... we don't wanna model a GS as a satellite
			}

			input, hasInput := solarInputs[instance.InstanceID]
			if !hasInput {
				logrus.Infof("PowerModule DEBUG: instance %s has valid spec but no solar_input entry found", instance.InstanceID)
				continue
			}

			battCfg, battOK := batteryConfigFromExtra(instance.Extra)
			if !battOK {
				logrus.Warnf("PowerModule: instance %s has no valid battery config, skipping battery calc", instance.InstanceID)
				continue
			}

			// call the energy caclulation models
			generated := generationModel.Generate(spec, input.SunAngleRad)
			consumed := consumptionModel.Consume(spec, energy.ConsumptionInput{
				Utilization:      input.Utilization,
				HasGroundContact: input.HasGroundContact,
				TxRateBps:        input.TxRateBps,
			})
			netPowerW := generated - consumed

			// --- Battery: linear integration using the SolarInput's own
			// Timestamp, not the tick interval, so a slow/uneven upstream
			// cadence never shows up as a timing error in the energy math.
			prevWh, hasPrev := batteryWh[instance.InstanceID]
			prevTS, hasTS := lastTimestamp[instance.InstanceID]

			var newWh float64
			switch {
			case !hasPrev || !hasTS:
				// first time seeing this instance — no prior sample to
				// diff against, initialize full (physically: starts a
				// mission fully charged)
				newWh = battCfg.CapacityWh
			default:
				dtSeconds := input.Timestamp - prevTS
				switch {
				case dtSeconds > 0:
					dtHours := dtSeconds / 3600.0
					deltaWh := netPowerW * dtHours
					newWh = prevWh + deltaWh
				case dtSeconds == 0:   // timestamp didn't change
					// SolarInput hasn't been re-measured since last tick
					// (Python loop slower than this tick) — hold steady
					// rather than updating battery
					newWh = prevWh
				default:
					// clock went backwards somehow — don't integrate
					// garbage, just log and hold
					logrus.Warnf("PowerModule: instance %s timestamp went backwards (prev=%.2f new=%.2f), holding battery steady", instance.InstanceID, prevTS, input.Timestamp)
					newWh = prevWh
				}
			}

			// Clamp in Wh — the panel doesn't "overproduce and store
			// extra somewhere," surplus above capacity is simply lost,
			// and a battery can't discharge below empty.
			if newWh > battCfg.CapacityWh {
				newWh = battCfg.CapacityWh
			} else if newWh < 0 {
				newWh = 0
			}

			batteryWh[instance.InstanceID] = newWh
			lastTimestamp[instance.InstanceID] = input.Timestamp

			// Percent is derived here, only for display/threshold check —
			// never stored, never fed back into the next tick's math.
			percent := (newWh / battCfg.CapacityWh) * 100.0

			if percent < battCfg.ThresholdPercent {
				logrus.Warnf("PowerModule: instance %s battery at %.1f%%, below threshold %.1f%% — would pause container here (pause/unpause not implemented yet)", instance.InstanceID, percent, battCfg.ThresholdPercent)
			}

			status := model.PowerStatus{
				GeneratedPowerW: generated,
				ConsumedPowerW:  consumed,
				NetPowerW:       generated - consumed,
				BatteryPercent:  percent,
			}
			
			// Write Result back into etcd
			err = synchronizer.PutInstancePower(instance.InstanceID, status)
			if err != nil {
				logrus.Errorf("PowerModule: put power status for %s error: %s", instance.InstanceID, err.Error())
			} else {
				logrus.Infof("PowerModule DEBUG: ts=%.2f instance=%s gen=%.2fW consume=%.2fW battery=%.2f%% (%.2f/%.2f Wh)",
							input.Timestamp,
							instance.InstanceID,
							generated,
							consumed,
							percent,
							newWh,
							battCfg.CapacityWh,
						)
			}
		}
	}
}