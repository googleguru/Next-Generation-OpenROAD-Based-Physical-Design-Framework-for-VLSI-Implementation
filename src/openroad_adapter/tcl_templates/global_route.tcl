## global_route.tcl — global routing with congestion management

read_lef  {{ pdk_lef }}
{% for extra_lef in extra_lefs | default([]) %}
read_lef  {{ extra_lef }}
{% endfor %}
read_liberty {{ lib_file }}
read_db {{ work_dir }}/cts/cts.odb
read_sdc {{ work_dir }}/cts/cts.sdc

set_wire_rc \
    -clock  -layer {{ clock_wire_layer  | default("metal5") }} \
    -signal -layer {{ signal_wire_layer | default("metal3") }}

global_route \
    -guide_file {{ work_dir }}/global_route/route.guide \
    -congestion_iterations {{ routing_overflow_iter | default(50) }} \
    -congestion_report_file {{ work_dir }}/global_route/congestion.rpt \
    -verbose 1 \
    {% if allow_congestion | default(false) %}
    -allow_congestion \
    {% endif %}
    -seed {{ seed | default(42) }}

estimate_parasitics -global_routing

report_worst_slack -max -digits 3
report_worst_slack -min -digits 3
report_tns -digits 3
report_net_fanout -high_fanout

{% if repair_post_groute | default(true) %}
repair_timing \
    -setup \
    -hold \
    -slack_margin {{ post_route_slack_margin | default(0.0) }}
detailed_placement
check_placement -verbose
{% endif %}

write_def  {{ work_dir }}/global_route/groute.def
write_db   {{ work_dir }}/global_route/groute.odb

set overflow [rsz::get_global_route_overflow]
set wirelength [rsz::get_global_route_wirelength]
puts "METRIC: overflow=${overflow}"
puts "METRIC: wirelength=${wirelength}"
