## finish.tcl — final verification, reporting, GDSII export

read_lef  {{ pdk_lef }}
{% for extra_lef in extra_lefs | default([]) %}
read_lef  {{ extra_lef }}
{% endfor %}
read_liberty {{ lib_file }}
read_db {{ work_dir }}/detail_route/droute.odb
read_sdc {{ work_dir }}/cts/cts.sdc

set_wire_rc \
    -clock  -layer {{ clock_wire_layer  | default("metal5") }} \
    -signal -layer {{ signal_wire_layer | default("metal3") }}

estimate_parasitics -global_routing

## Final timing
report_worst_slack -max -digits 4 > {{ work_dir }}/finish/final_timing.rpt
report_worst_slack -min -digits 4 >> {{ work_dir }}/finish/final_timing.rpt
report_tns -digits 4               >> {{ work_dir }}/finish/final_timing.rpt
report_check_types -max_slew -max_capacitance -max_fanout \
    >> {{ work_dir }}/finish/final_timing.rpt

## Power estimation
estimate_power
report_power >> {{ work_dir }}/finish/final_timing.rpt

## DRC / antenna check
check_antennas \
    -report_file {{ work_dir }}/finish/final_drc.rpt \
    {% if fix_antennas | default(true) %}
    -repair \
    {% endif %}
    -iterations {{ antenna_fix_iter | default(3) }}

## Write outputs
write_def  {{ work_dir }}/finish/final.def
write_db   {{ work_dir }}/finish/final.odb

{% if write_gds | default(false) %}
if { [info commands write_gds] ne "" } {
    write_gds \
        -merge {{ merge_gds | default("") }} \
        {{ work_dir }}/finish/final.gds
}
{% endif %}

set wns [sta::get_wns -max]
set tns [sta::get_tns -max]
puts "METRIC: wns=${wns}"
puts "METRIC: tns=${tns}"
report_design_area
puts "Flow finish complete."
