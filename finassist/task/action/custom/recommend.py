"""
    @Aythor:Bee
    @Time:2026/11/14
    @Desc:相似商品推荐的占位实现。
          yaml 里 similar_product_recommendation 的 action 步骤写的是
          action_recommend_similar_products，但课程到 day06 还没做这个能力。
          不注册的话那条流程一走到 action 就 KeyError（整轮请求 500），
          所以先注册一个占位：只写一句"还没接"，保证流程能正常走到 end。
"""
from finassist.domain.state import DialogueState
from finassist.task.action.base import Action, ActionResult


class RecommendProductsAction(Action):
    name = "action_recommend_similar_products"

    async def run(self, state: DialogueState) -> ActionResult:
        product_id = state.tasks.active.slots.get("product_id")
        return ActionResult(
            slots_update={
                "recommendation_summary": (
                    f"（相似商品推荐还没接入中台，当前商品 id：{product_id}）"
                ),
            }
        )
