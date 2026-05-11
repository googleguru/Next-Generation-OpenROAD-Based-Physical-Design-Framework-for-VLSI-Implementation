## detail_route.tcl — detailed routing

read_lef  {{ pdk_lef }}
{% for extra_lef in extra_lefs | default([]) %}
read_lef  {{ extra_lef }}
{% endfor %}
read_liberty {{ lib_file }}
read_db {{ work_dir }}/global_route/groute.odb
read_sdc {{ work_dir }}/cts/cts.sdc

detailed_route \
    -input_guide       {{ work_dir }}/global_route/route.guide \
    -output_drc        {{ work_dir }}/detail_route/droute_drc.rpt \
    -output_maze       {{ work_dir }}/detail_route/droute_maze.log \
    -bottom_routing_layer {{ bottom_layer | default("metal1") }} \
    -top_routing_layer    {{ top_layer    | default("metal9") }} \
    -end_iteration     {{ droute_end_iter | default(64) }} \
    -via_in_pin_bottom_layer_num {{ via_in_pin_bot | default(1) }} \
    -via_in_pin_top_layer_num    {{ via_in_pin_top | default(3) }} \
    -verbose 1

report_design_area

set drc_count [drt::get_drc_count]
puts "METRIC: drc_violations=${drc_count}"

write_def  {{ work_dir }}/detail_route/droute.def
write_db   {{ work_dir }}/detail_route/droute.odb

puts "Detailed routing complete. DRC violations: ${drc_count}"
