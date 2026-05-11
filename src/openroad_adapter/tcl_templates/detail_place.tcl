## detail_place.tcl — detailed placement and timing-driven repair

read_lef  {{ pdk_lef }}
{% for extra_lef in extra_lefs | default([]) %}
read_lef  {{ extra_lef }}
{% endfor %}
read_liberty {{ lib_file }}
read_db {{ work_dir }}/global_place/gplace.odb
read_sdc {{ work_dir }}/synthesis/synth.sdc

set_wire_rc \
    -clock  -layer {{ clock_wire_layer  | default("metal5") }} \
    -signal -layer {{ signal_wire_layer | default("metal3") }}

estimate_parasitics -placement

detailed_placement \
    -max_displacement {{ max_displacement | default(5) }} \
    {% if mirror_instances | default(true) %}
    -mirror_instances \
    {% endif %}
    -seed {{ seed | default(42) }}

check_placement -verbose

estimate_parasitics -placement
report_worst_slack -max -digits 3
report_worst_slack -min -digits 3
report_tns -digits 3

{% if repair_timing | default(true) %}
repair_timing \
    -setup \
    -hold \
    -slack_margin {{ slack_margin | default(0.0) }} \
    -max_buffer_percent {{ max_buffer_percent | default(20) }}
detailed_placement -max_displacement {{ max_displacement | default(5) }}
check_placement -verbose
{% endif %}

write_def  {{ work_dir }}/detail_place/dplace.def
write_db   {{ work_dir }}/detail_place/dplace.odb

set wns [sta::get_wns -max]
set tns [sta::get_tns -max]
puts "METRIC: wns=${wns}"
puts "METRIC: tns=${tns}"
report_design_area
