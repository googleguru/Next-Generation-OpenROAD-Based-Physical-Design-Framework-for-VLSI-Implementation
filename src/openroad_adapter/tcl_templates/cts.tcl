## cts.tcl — clock tree synthesis and post-CTS timing repair

read_lef  {{ pdk_lef }}
{% for extra_lef in extra_lefs | default([]) %}
read_lef  {{ extra_lef }}
{% endfor %}
read_liberty {{ lib_file }}
read_db {{ work_dir }}/detail_place/dplace.odb
read_sdc {{ work_dir }}/synthesis/synth.sdc

set_wire_rc \
    -clock  -layer {{ clock_wire_layer  | default("metal5") }} \
    -signal -layer {{ signal_wire_layer | default("metal3") }}

configure_cts_characterization \
    -max_slew  {{ cts_max_slew    | default(0.25)   }} \
    -max_cap   {{ cts_max_cap     | default(0.02)   }} \
    -slew_inter {{ cts_slew_inter | default(0.05)   }} \
    -cap_inter  {{ cts_cap_inter  | default(0.004)  }}

clock_tree_synthesis \
    -root_buf  {{ cts_root_buf    | default("BUF_X4")  }} \
    -buf_list  "{{ cts_buf_list   | default('BUF_X2 BUF_X4 BUF_X8') }}" \
    -wire_unit {{ cts_wire_unit   | default(20) }} \
    -sink_clustering_enable \
    -sink_clustering_size    {{ cts_cluster_size   | default(20) }} \
    -sink_clustering_max_diameter {{ cts_cluster_diam | default(50.0) }} \
    -distance_between_buffers {{ cts_buf_distance | default(100) }}

set_propagated_clock [all_clocks]

estimate_parasitics -placement

repair_clock_nets

estimate_parasitics -placement

report_clock_skew
report_worst_slack -max -digits 3
report_worst_slack -min -digits 3
report_tns

{% if repair_post_cts | default(true) %}
repair_timing \
    -setup \
    -hold \
    -slack_margin {{ post_cts_slack_margin | default(0.1) }}
detailed_placement
check_placement -verbose
{% endif %}

write_def  {{ work_dir }}/cts/cts.def
write_db   {{ work_dir }}/cts/cts.odb

write_sdc  {{ work_dir }}/cts/cts.sdc

set wns  [sta::get_wns -max]
set tns  [sta::get_tns -max]
set skew [cts::get_clock_skew]
puts "METRIC: wns=${wns}"
puts "METRIC: tns=${tns}"
puts "METRIC: skew_ps=[expr {${skew} * 1000.0}]"
