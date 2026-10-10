# coding=utf-8
"""
    @project: MaxKB
    @Author：虎
    @file： i_reranker_node.py
    @date：2024/9/4 10:40
    @desc:
"""
from typing import Type

from rest_framework import serializers

from application.flow.common import WorkflowMode
from application.flow.i_step_node import INode, NodeResult

from django.utils.translation import gettext_lazy as _


from application.context.serializers import ContextPolicySerializer


class RerankerSettingSerializer(serializers.Serializer):
    context_policy = ContextPolicySerializer(required=False)
    # 需要查询的条数
    top_n = serializers.IntegerField(required=True,
                                     label=_("Reference segment number"))
    # 相似度 0-1之间
    similarity = serializers.FloatField(required=True, max_value=2, min_value=0,
                                        label=_("Reference segment number"))
    max_paragraph_char_number = serializers.IntegerField(required=True,
                                                         label=_("Maximum number of words in a quoted segment"))


class RerankerStepNodeSerializer(serializers.Serializer):
    reranker_setting = RerankerSettingSerializer(required=True)
    retrieval_budget_reference = serializers.ListField(required=False, child=serializers.CharField(),
                                                       allow_empty=True, allow_null=True)

    question_reference_address = serializers.ListField(required=True)
    reranker_model_id = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    reranker_model_id_type = serializers.CharField(required=False, default='custom')
    reranker_model_id_reference = serializers.ListField(required=False, child=serializers.CharField(), allow_empty=True)
    reranker_reference_list = serializers.ListField(required=True, child=serializers.ListField(required=True))
    show_knowledge = serializers.BooleanField(required=True,
                                              label=_("The results are displayed in the knowledge sources"))

    def is_valid(self, *, raise_exception=False):
        super().is_valid(raise_exception=True)


class IRerankerNode(INode):
    type = 'reranker-node'
    support = [WorkflowMode.APPLICATION, WorkflowMode.APPLICATION_LOOP, WorkflowMode.TOOL, WorkflowMode.TOOL_LOOP]

    def get_node_params_serializer_class(self) -> Type[serializers.Serializer]:
        return RerankerStepNodeSerializer

    def _run(self):
        question = self.workflow_manage.get_reference_field(
            self.node_params_serializer.data.get('question_reference_address')[0],
            self.node_params_serializer.data.get('question_reference_address')[1:])
        reranker_list = [self.workflow_manage.get_reference_field(
            reference[0],
            reference[1:]) for reference in
            self.node_params_serializer.data.get('reranker_reference_list')]

        node_params_data = dict(self.node_params_serializer.data)

        budget_reference = node_params_data.pop('retrieval_budget_reference', []) or []
        decision = None
        if budget_reference:
            references = node_params_data['reranker_reference_list']
            if (len(budget_reference) != 2 or budget_reference[1] != 'retrieval_budget'
                    or references != [[budget_reference[0], 'retrieved_paragraph_list']]):
                raise ValueError('动态预算必须关联同一检索节点的 retrieval_budget 和唯一的 retrieved_paragraph_list')
            decision = self.workflow_manage.get_reference_field(budget_reference[0], budget_reference[1:])
            if decision is not None and (not isinstance(decision, dict) or decision.get('version') not in (1, 2)
                                         or decision.get('question') != str(question)):
                raise ValueError('动态检索预算与当前重排问题不匹配')
            # Disabled source: resolve its ordinary output, retaining legacy reranker behavior.
            if decision is None:
                reranker_list = [self.workflow_manage.get_reference_field(budget_reference[0], ['paragraph_list'])]
        node_params_data['retrieval_budget'] = decision
        dynamic = decision is not None and decision['rerank'] is not None
        skip = dynamic and not decision['rerank']

        reranker_model_id_type = node_params_data.pop('reranker_model_id_type', None)
        reranker_model_id_reference = node_params_data.pop('reranker_model_id_reference', None)
        reranker_model_id = node_params_data.pop('reranker_model_id', None)

        # 处理引用类型
        if not skip and reranker_model_id_type == 'reference' and reranker_model_id_reference:
            reference_data = self.workflow_manage.get_reference_field(
                reranker_model_id_reference[0],
                reranker_model_id_reference[1:],
            )
            if reference_data and isinstance(reference_data, dict):
                reranker_model_id = reference_data.get('reranker_model_id',
                                                       reference_data.get('model_id', reranker_model_id))
        elif not skip and reranker_model_id_type == 'default':
            default_setting = self.workflow_manage.get_default_model_setting('RERANKER')
            reranker_model_id = default_setting.get('model_id')
        if not dynamic and (reranker_model_id is None or reranker_model_id == ''):
            raise Exception(_('Model is not allowed to be empty'))

        return self.execute(**node_params_data, question=str(question),
                            reranker_list=reranker_list, reranker_model_id=reranker_model_id)

    def execute(self, question, reranker_setting, reranker_list, reranker_model_id, show_knowledge,
                **kwargs) -> NodeResult:
        pass
