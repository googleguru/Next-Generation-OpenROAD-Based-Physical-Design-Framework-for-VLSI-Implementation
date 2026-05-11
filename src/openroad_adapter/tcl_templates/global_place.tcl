## global_place.tcl — global placement with density and timing-driven knobs

read_lef  {{ pdk_lef }}
{% for extra_lef in extra_lefs | default([]) %}
read_lef  {{ extra_lef }}
{% endfor %}
read_liberty {{ lib_file }}
read_db {{ work_dir }}/pdn/pdn.odb
read_sdc {{ work_dir }}/synthesis/synth.sdc

set_wire_rc \
    -clock  -layer {{ clock_wire_layer | default("metal5") }} \
    -signal -layer {{ signal_wire_layer | default("metal3") }}

estimate_parasitics -placement

global_placement \
    -skip_initial_place \
    -density          {{ target_density     | default(0.70) }} \
    -pad_left         {{ pad_left           | default(2)    }} \
    -pad_right        {{ pad_right          | default(2)    }} \
    {% if timing_driven | default(true) %}
    -timing_driven \
    {% endif %}
    {% if routability_driven | default(true) %}
    -routability_driven \
    {% endif %}
    -seed             {{ seed | default(42) }}

{% if run_repair_before_dp | default(false) %}
estimate_parasitics -placement
repair_design -max_wire_length {{ max_wire_length | default(800) }}
{% endif %}

write_def  {{ work_dir }}/global_place/gplace.def
write_db   {{ work_dir }}/global_place/gplace.odb

report_design_area
set overflow [format "%.4f" [gpl::get_overflow]]
puts "METRIC: overflow=${overflow}"
puts "METRIC: hpwl=[format %.2f [gpl::get_hpwl]]"
