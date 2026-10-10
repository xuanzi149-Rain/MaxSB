from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('application', '0018_merge_evaluation')]
    operations = [
        migrations.AlterField('chatrecord', 'message_tokens',
                              models.IntegerField(default=0, null=True, verbose_name='请求token数量')),
        migrations.AlterField('chatrecord', 'answer_tokens',
                              models.IntegerField(default=0, null=True, verbose_name='响应token数量')),
    ]
